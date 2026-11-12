# Spec Delta

## Purpose

定义训练业务记录（TrainingSession）的建立、归属不可变、可观察状态机与取消语义，使云端成为训练会话的最终业务权威，并为多机位录像、资源级授权和后续上传提供稳定父记录。

## ADDED Requirements

### Requirement: Session creation with server-derived scope

创建训练会话 SHALL 由云端从已认证身份与路径中已校验的机构/场馆写入 tenant_id、site_id、created_by_user_id、status 与全部服务端时间；请求体中的归属、创建者、状态与历史时间字段 MUST 被拒绝而非忽略。

#### Scenario: Server fills ownership and status

- **WHEN** 具该 Site 访问权的 Coach 或本机构 Owner/Admin 提交仅含可选 title 的创建请求
- **THEN** 服务 MUST 返回 201 与 `status=planned`、`started_at/completed_at/cancelled_at=null`，且 created_by_user_id 等于当前认证用户

#### Scenario: Client attempts to self-assign ownership

- **WHEN** 创建请求包含 tenant_id、site_id、created_by_user_id、status、created_at 或 started_at 中任一字段
- **THEN** 服务 MUST 返回 422 且不创建会话

#### Scenario: Non-member or foreign site

- **WHEN** 调用者不是该机构成员，或该 Site 属于另一机构/另一场馆
- **THEN** 服务 MUST 返回 404 且不泄露该机构或场馆是否存在

### Requirement: Session state machine and terminal immutability

Session 状态 SHALL 仅允许 planned → recording → completed 以及 planned 或 recording → cancelled；completed 与 cancelled MUST 为不可回退的终态，合法枚举但不允许迁移的目标 MUST 返回 409。

#### Scenario: Forward progression

- **WHEN** 具 S-manage 的调用者把 planned 会话依次改为 recording、再改为 completed
- **THEN** 服务 MUST 各返回 200，转入 recording 时写入 started_at，转入 completed 时写入 completed_at

#### Scenario: Skipping or leaving a terminal state

- **WHEN** 调用者请求 planned → completed，或在 completed/cancelled 之后请求任何其他状态
- **THEN** 服务 MUST 返回 409 `state_conflict` 且会话状态与时间字段保持不变

#### Scenario: Repeating the current status

- **WHEN** 调用者提交与当前状态相同的 status
- **THEN** 服务 MUST 返回 200 且不新增时间字段、不产生额外终态副作用

### Requirement: Session PATCH surface is closed

Session 的可写集合 SHALL 仅为 title 与 status；空 PATCH 或仅含 null 的 PATCH MUST 返回 422，归属、创建者、历史时间与未知字段 MUST 被拒绝。

#### Scenario: Title-only patch

- **WHEN** 具 S-manage 的调用者仅提交新的 title
- **THEN** 服务 MUST 返回 200，title 更新且 status 与全部时间字段不变

#### Scenario: Empty or null patch

- **WHEN** 调用者提交空对象或 `{"title": null}`
- **THEN** 服务 MUST 返回 422 且不修改记录

### Requirement: Cancellation closes unfinished uploads

取消 Session SHALL 在同一事务内把该 Session 下所有未终结的上传会话置为 failed 且原因为 session_cancelled，并把其尚未 ready 的 VideoAsset 置为 failed；不允许出现 Session 已 cancelled 而 Asset 仍为 pending_upload 的可见状态。

#### Scenario: Cancel with in-flight upload intent

- **WHEN** 具 S-manage 的调用者取消一个仍有 `uploading` 上传会话的 planned 或 recording 会话
- **THEN** 服务 MUST 提交 cancelled 状态、该上传会话的 failed/session_cancelled 与对应 Asset 的 failed，且三者要么全部可见要么全不可见

#### Scenario: Repeat cancel is idempotent

- **WHEN** 调用者再次取消同一已 cancelled 会话
- **THEN** 服务 MUST 返回 200，且不得回退状态、不得重复改写已终结上传的原因或时间

#### Scenario: Upload intent after cancellation

- **WHEN** 调用者在已 cancelled 或已 completed 的会话上请求创建上传意图
- **THEN** 服务 MUST 返回 409 `state_conflict` 且不创建 Asset 或 UploadSession
