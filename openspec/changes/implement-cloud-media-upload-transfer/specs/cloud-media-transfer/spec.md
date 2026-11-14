# Spec Delta

## Purpose

为已登记的单个媒体逻辑资产提供私有对象存储、可恢复分片传输、服务端完整对象验证和失败清理，使数据库中的可用状态与实际对象一致，同时保持用户、节点及租户资源边界，并为中断、并发和崩溃提供可审计的恢复结果。

## ADDED Requirements

### Requirement: Private provider independent object storage

媒体业务 SHALL 通过统一存储协议访问私有对象；对象位置与物理上传标识 MUST 由服务端绑定到既有 UploadSession 的 Tenant/Site/Asset，调用者 MUST NOT 指定桶、对象路径、provider 或通用存储凭据。存储能力不满足必需的分片、精确对象读取与清理保证时 MUST 拒绝启用传输，不得回退公开静态目录。

#### Scenario: Object scope cannot be injected
- **WHEN** 用户或 Edge 传入其他机构的 upload ID，或在分片请求中传入 bucket/key/provider
- **THEN** 前者 MUST 按当前可见范围返回 404，后者 MUST 返回 422，且不得对任意对象签名或发起物理写入

#### Scenario: Incomplete storage capability
- **WHEN** 配置的存储不支持精确对象身份、分片恢复或安全清理
- **THEN** 服务 MUST 拒绝启用相应媒体能力并给出配置错误，既有身份和元数据操作不得获得公开文件旁路

### Requirement: Transfer preparation is recoverable

首次申请分片 SHALL 为该 UploadSession 保留唯一业务存储记录与固定布局；物理准备未完成时 MUST 返回 202 与可查询状态，完成后返回 200 与分片 URL。超时、响应丢失或重试 MUST 不创建第二个逻辑 Asset、延长意图期限或遗失无法追踪的物理上传。

#### Scenario: Preparation response is lost
- **WHEN** 存储已创建 multipart 但服务端在保存响应前崩溃，原发起主体重试
- **THEN** 恢复流程 MUST 追踪或回收本次作用域的多余物理句柄，只保留一个被选定的传输绑定，Asset 与 UploadSession ID MUST 不变

#### Scenario: Existing intent exceeds transfer policy
- **WHEN** M2 已有未终结意图超出当前已批准的传输大小策略
- **THEN** 准备 MUST 返回 409 `transfer_policy_conflict` 而不删改历史声明；读取、中止和过期仍可用；新增意图不符合已批准策略时 MUST 返回 422

### Requirement: Bounded multipart layout and part credentials

服务 SHALL 根据声明总大小与已批准配置固定分片布局；编号 MUST 从 1 连续覆盖对象，除末片外大小固定，末片按剩余字节确定，范围与数量 MUST 同时满足服务策略和 provider 限制。分片 URL MUST 仅允许目标上传的指定 part 动作，不能合并、读取或删除对象，也不能延长 UploadSession。

#### Scenario: Invalid part request
- **WHEN** 请求含重复、零、负数、越界编号，过多编号或不符合布局的大小
- **THEN** 服务 MUST 返回 422 且不签发任何 URL；合法批次可乱序上传，最终合并顺序仍按编号

#### Scenario: Bounded signing and expired identity
- **WHEN** 原发起主体申请有效分片 URL，之后身份撤销或会话过期
- **THEN** 签名到期时间 MUST 不超过配置上限、该上传 expires_at 和签发时身份有效期的最小值；后续申请 MUST 重认证并拒绝失效身份，已签 URL 不能使终态上传重新可完成

### Requirement: Part confirmation uses provider evidence

分片登记与确认 SHALL 绑定既定布局；确认 MUST 核对 provider 中该精确 multipart 的实际编号、大小与回执。相同分片的相同确认重复请求 MUST 返回同一确认结果且不重写首次确认时间；不同回执或大小 MUST 返回冲突。客户端回执与 provider ETag MUST NOT 被当作完整对象 SHA-256。

#### Scenario: Repeated confirmation
- **WHEN** 原发起主体以相同编号、大小与 ETag 重复或并发确认
- **THEN** 服务 MUST 返回 200，只有一条确认记录，首次确认时间不变；同编号不同内容 MUST 返回 409 `part_conflict`

#### Scenario: Claimed part does not exist
- **WHEN** 客户端确认一个 provider 尚不存在、大小不符或回执不符的分片
- **THEN** 服务 MUST 返回 409 `part_not_confirmed`，不得记为已确认或使 Asset ready；provider 暂时不可用 MUST 返回可重试错误而非伪造不存在

### Requirement: Resume queries reconcile all parts

原发起主体 SHALL 能查询服务端核对过的分片并补传缺失部分；恢复 MUST 分页遍历 provider 结果，不能只检查第一页。查询与确认 MUST 执行当前身份/归属检查，客户端本地进度不能覆盖已提交终态。

#### Scenario: Network interruption and lost receipt
- **WHEN** 若干分片已传入 provider 但本地丢失回执，调用者恢复连接并查询分片
- **THEN** 服务 MUST 返回真实核对的编号、大小、ETag 与续页标记，调用者可补传缺失部分，原 Asset/UploadSession/期限保持不变

#### Scenario: Provider part changed after confirmation
- **WHEN** 已确认分片在 provider 侧被未过期 URL 重传替换，或 complete 使用过时清单
- **THEN** 服务 MUST 识别不一致并拒绝使用过时证据，不能仅依据数据库中的旧确认使 Asset ready

### Requirement: Complete accepts one immutable manifest

complete SHALL 要求 Idempotency-Key 与完整、有序、无重复的分片清单，并核对已确认分片及真实 provider 状态。同一主体/作用域/键同摘要 MUST 重放当前结果，异摘要 MUST 返回 409 `idempotency_conflict`；首次被接受的清单不可替换，不同键同清单也只能驱动同一次完成流程。

#### Scenario: Accepted complete is asynchronous
- **WHEN** 原发起主体对 uploading 提交合规完整清单
- **THEN** 服务 MUST 持久提交 completing、清单摘要及可恢复工作后返回 202，响应包含原 asset/upload ID 和轮询位置，不得此时声明 ready

#### Scenario: Repeat complete during and after verification
- **WHEN** 相同清单在 completing 期间或 completed 后重复提交
- **THEN** 前者 MUST 返回 202 且不产生第二次业务完成，后者 MUST 返回 200 与同一 completed/ready 结果；不同清单 MUST 返回 409，失败终态 MUST 不被复活

#### Scenario: Incomplete or reordered manifest
- **WHEN** complete 含缺失分片、重复编号、非法顺序或未确认分片
- **THEN** 结构/边界非法 MUST 返回 422，合法结构但证据未齐 MUST 返回 409 `part_not_confirmed`，不得接受完成作业

### Requirement: Whole object bytes determine verification

服务 SHALL 从绑定的不可变完整对象或精确版本读取所有字节，独立计算实际大小与整对象 SHA-256，探测真实媒体类型并按批准的类型策略检查声明。HEAD、客户端 checksum、ETag、分片回执或 multipart 合并成功 MUST NOT 替代该校验；验证与最终访问 MUST 指向同一对象身份。

#### Scenario: Matching object
- **WHEN** 合并后的全部字节、SHA-256 和真实媒体类型均符合声明及媒体策略
- **THEN** 系统 MUST 留存验证结果与精确对象身份，才允许最终提交 ready，不得把验证值写入设备采集时间

#### Scenario: False checksum or disguised media
- **WHEN** 实际大小或 SHA-256 不符，或文件真实类型不允许、与具体声明不符、媒体探测失败
- **THEN** 系统 MUST 原子提交 UploadSession.failed 与 Asset.failed，原因 `validation_failed`，不签发访问 URL并登记残留清理；安全错误细节不得泄露对象位置

#### Scenario: Ambiguous storage completion
- **WHEN** provider 合并超时、返回带错误内容的成功 HTTP 状态，或重试收到 NoSuchUpload
- **THEN** 服务 MUST 核对精确对象与真实结果，不能仅凭状态码或上传标识消失报告成功；不确定结果 MUST 保持可恢复、不可 ready

### Requirement: Final verification commits both terminal states

只有整对象验证成功且当前 Session 未取消、上传未过期/终结、工作代际仍有效、物理对象未进入清理时，系统 SHALL 在同一数据库事务提交 UploadSession.completed 与 VideoAsset.ready 及验证值/引用。任一写入或提交失败 MUST 不出现单侧终态，重试 MUST 返回唯一已提交结果。

#### Scenario: Final transaction fails
- **WHEN** 写 UploadSession、Asset 或物理引用时注入失败
- **THEN** 整个最终事务 MUST 回滚，两侧不得分别可见；重试可复用同一已验证对象，但 MUST 重新核对当前状态与精确身份

#### Scenario: Replaced or missing object
- **WHEN** 验证后、终态提交前，对象版本/身份已改变或无法确认
- **THEN** 服务 MUST 不提交 ready；访问不能回退到同 key 的最新未知对象

### Requirement: Terminal races have one legal winner

Cancel、Abort、Expiry 与完整验证最终提交 SHALL 按同一 scoped 并发协议裁定；服务端 now 达到 expires_at 时 uploading 与 completing 均 MUST 可终结为 expired。首次失败/中止/过期原因与时间不可被后到请求改写；complete 接受为 completing 不等于最终提交已获胜。

#### Scenario: Cancel or abort wins before final commit
- **WHEN** Session 取消或上传中止先于校验最终事务提交
- **THEN** 上传与尚未 ready 的 Asset MUST 原子失败，后到 complete MUST 返回 409 `upload_not_completable`，旧 worker 不得写回 completed/ready

#### Scenario: Complete wins before later cancellation
- **WHEN** 整对象验证最终事务先提交 completed/ready，之后取消 Session 或中止上传
- **THEN** ready 对象、验证值及首次终态 MUST 保留，后到操作不得删除或回退该资产

#### Scenario: Deadline is crossed during verification
- **WHEN** 校验已开始但提交前服务端 now 恰好达到或超过 expires_at
- **THEN** UploadSession MUST 终结为 expired、Asset 同事务 failed，继续读取或 complete 不得延期或覆盖首次原因

### Requirement: Crashed and duplicate workers recover safely

持久工作 SHALL 在进程重启、超时与重复投递后恢复，旧工作者不得越过已失效代际发布终态。存储 I/O 与数据库没有分布式原子提交保证，系统 MUST 显式对账，不能依赖进程内任务存活或宣称物理副作用恰好一次。耗尽有界重试的完成工作 MUST 失败配对并保留可诊断证据。

#### Scenario: Crash after object assembly
- **WHEN** provider 已合并对象、数据库尚未最终完成时进程崩溃
- **THEN** 新工作者 MUST 发现同一对象、重新验证并重新检查业务终态，只能提交一次 completed/ready 或保留已获胜失败终态

#### Scenario: Lease expires and old worker returns
- **WHEN** 新工作者取得恢复权后旧工作者提交结果
- **THEN** 旧结果 MUST 被拒绝，不得覆盖新代际、取消或清理结果，也不能删除获胜代际的有效对象

### Requirement: Completion authority is current at publication

完整对象验证最终提交 SHALL 重查发起用户当前成员/Site/S-manage及接受complete的身份有效性，或原节点/Device状态及接受凭据有效性。若在最终提交前失权，系统 MUST 以upload_failed配对失败并登记清理，不能因请求曾被接受而发布ready；已先成功完成的历史对象仍按当前A-read控制访问。

#### Scenario: Authority is lost while bytes are verified
- **WHEN** completing期间用户失去成员/角色/Site权限、接受身份到期/撤销，或节点/来源设备停用
- **THEN** 最终提交 MUST 不产生ready，上传和Asset MUST 配对failed/upload_failed并留安全审计，原来源与采集时间不得改写

#### Scenario: Earlier successful completion is immutable
- **WHEN** completed/ready已先成功提交，之后主体权限或凭据失效
- **THEN** 历史终态和验证引用 MUST 保留，后续公开操作按当前身份/授权拒绝，不得把历史ready回退为failed

### Requirement: Expiry and cleanup are retryable and scoped

清扫 SHALL 可重试地终结过期 uploading/completing，并回收本作用域未完成 multipart 与失败残留。每次删除前 MUST 核对精确物理身份、全部有效逻辑引用、当前终态与仍可能写入的签名窗口；范围不明、provider 权限/网络错误或删除未确认 MUST 留待重试并报告失败，不能默认 absent。

#### Scenario: Failed cleanup is visible
- **WHEN** abort/delete/删除后 HEAD 检查遇到权限、daemon/网络类错误或对象仍存在
- **THEN** 清扫 MUST 不报告成功，持久记录重试/告警，显式 CLI 批次 MUST 非零退出；业务失败终态不得因此恢复为 uploading

#### Scenario: Late upload after abort
- **WHEN** 已签 part URL 在逻辑 abort 后仍产生分片或迟到对象
- **THEN** 对象 MUST 不可被公开读取或使 Asset ready；清扫 MUST 在写入窗口之后再次对账并精确回收

### Requirement: Orphan collection cannot delete retained assets

孤儿识别 SHALL 使用本项目命名空间、可信对象元数据、持久观察与宽限后再次核验；年龄或对象前缀相同不足以直接删除。仍被任意有效逻辑 Asset 引用、属于活动上传/验证、身份不明或归属不符的对象 MUST 不被删除。清理技术残留 MUST NOT 自动实现业务保留到期或删除 Edge 本地原件。

#### Scenario: Object is still referenced
- **WHEN** 候选对象在删除前存在任何需保留 Asset 引用，或有活动完成工作
- **THEN** 清理 MUST 拒绝删除，记录跳过原因，不得仅依引用计数缓存或单一 Asset 状态决策

#### Scenario: Unknown inventory object
- **WHEN** 存储扫描发现未登记物理句柄、无法验证归属或尚未过观察宽限
- **THEN** 系统 MUST 登记候选并等待重查或人工处理，不得进行全桶/全前缀批量删除

### Requirement: Transfer evidence uses real isolated backends

传输交付 SHALL 提供 SQLite 与 PostgreSQL 完整回归、真实隔离对象存储集成、服务端整对象摘要和清理证据。并发裁定 MUST 用真实 PostgreSQL 不同物理连接及可观察的锁/条件提交顺序证明，不能以单连接排队、纯 mock、跳过或客户端回执冒充通过。

#### Scenario: Concurrency evidence is genuine
- **WHEN** 验证 Cancel/Abort/Expiry 与 Complete 两种受控胜负顺序或重复分片/完成请求
- **THEN** 证据 MUST 含不同业务 backend PID、独立监控和实际阻塞/条件提交结果、有界超时及终态配对断言

#### Scenario: Required storage integration is missing
- **WHEN** 明确请求集成验收但隔离存储未就绪、归属不符、必需场景零收集或被跳过
- **THEN** 验收 MUST 失败并精确清理本次资源，报告绑定实际代码 SHA；不得连接业务桶或以数据库 CI 全绿代替传输验收
