# Spec Delta

## MODIFIED Requirements

### Requirement: Independent revocable edge credentials

Edge凭据 MUST 与User会话分离，仅授权所属Node的heartbeat及明确批准的原发起上传意图/传输/恢复/完成操作，并使用`Authorization: Bearer swim_edge_<opaque-token>`。每个媒体操作 SHALL 继续核验节点与资源同tenant/site及原发起主体，User与Edge凭据 MUST NOT 互用，不得因支持上传获得用户角色、他人上传或媒体读取权限。

#### Scenario: User and node identity separation
- **WHEN** User token用于Edge heartbeat或上传，或Edge token用于用户节点管理/既有基础API/用户媒体读取
- **THEN** 服务 MUST 返回401，节点凭据 MUST NOT 通过用户身份路径获得成员权限

#### Scenario: Node credential is not a general media credential
- **WHEN** 有效节点凭据请求其他节点的上传或跨tenant/site资源
- **THEN** 服务 MUST 返回404且无传输/签名副作用；该凭据生命周期、撤销及35天离线限制 MUST 保持原规则，不得自动续期
