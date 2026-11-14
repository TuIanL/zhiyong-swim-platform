# Spec Delta

## MODIFIED Requirements

### Requirement: Cancellation closes unfinished uploads

取消 Session SHALL 在同一事务内把该 Session 下所有未终结的上传会话置为 failed 且原因为 session_cancelled，并把其尚未 ready 的 VideoAsset 置为 failed；不允许出现 Session 已 cancelled 而 Asset 仍为 pending_upload 的可见状态。该规则 SHALL 同样覆盖 completing；已经完成验证并提交 ready 的资产 MUST 保留，不随 Session 取消删除或回退。

#### Scenario: Cancel with in-flight upload intent

- **WHEN** 具 S-manage 的调用者取消一个仍有 `uploading` 上传会话的 planned 或 recording 会话
- **THEN** 服务 MUST 提交 cancelled 状态、该上传会话的 failed/session_cancelled 与对应 Asset 的 failed，且三者要么全部可见要么全不可见

#### Scenario: Repeat cancel is idempotent

- **WHEN** 调用者再次取消同一已 cancelled 会话
- **THEN** 服务 MUST 返回 200，且不得回退状态、不得重复改写已终结上传的原因或时间

#### Scenario: Upload intent rejected after cancellation

- **WHEN** 调用者在已 cancelled 的会话上以未命中既有幂等记录的新键请求创建上传意图
- **THEN** 服务 MUST 返回 409 `state_conflict` 且不创建 Asset 或 UploadSession

#### Scenario: Existing intent can be replayed after cancel
- **WHEN** 当前仍有权的原用户或节点以同主体/作用域/键及相同摘要重试取消前已经创建的意图
- **THEN** 服务 MUST 返回原 Asset/UploadSession 的当前终态且不新增记录；同键异参 MUST 返回幂等冲突，不能先因 Session cancelled 掩盖该结果

#### Scenario: Cancel races with verification final commit
- **WHEN** Session cancel 与完整对象验证最终提交通过独立事务并发
- **THEN** 取消先提交 MUST 使 uploading/completing 与对应 pending Asset 同事务失败，验证先最终提交 MUST 保留 completed/ready；complete 接受为 completing 本身不得阻止取消
