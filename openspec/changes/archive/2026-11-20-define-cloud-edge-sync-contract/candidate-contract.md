# M4 v1 契约追溯

二轮评审时的 [候选契约历史版本](https://github.com/TuIanL/zhiyong-swim-platform/blob/a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b/openspec/changes/define-cloud-edge-sync-contract/candidate-contract.md) 保存在 Git。负责人签认并执行纯文档 Apply 后，以 [正式 API 契约](../../../../docs/contracts/cloud-edge-sync-v1.md) 为当前工程引用。R1–R8、19 个原始 Scenario 和 19 项 T/A/C/L 向量保留，Q5 B 保留 M1–M6，以 M7 补充多分片续传验收。

- [R1–R8 与场景](../../../../docs/contracts/cloud-edge-sync-v1.md#requirements)
- [双向协议样例](../../../../docs/contracts/cloud-edge-sync-v1.md#examples)
- [需求与媒体验收矩阵](../../../../docs/contracts/cloud-edge-sync-v1.md#acceptance-matrix)
- [负责人签认及 D1–D6 入口](design.md#decision-signoff)

## 首轮 Verify 后的契约追溯

[首轮 Verify](verification.md) 固定核验 `4588e6905ad876fb8bcc1edb5a3280f21703200a`。首轮后的纯文档修订补充以下向量，原编号保留。

- [W1.1–W1.7 取消后的离线补投](../../../../docs/contracts/cloud-edge-sync-v1.md#w1-vectors)
- [M7 人工批准后的多分片续传](../../../../docs/contracts/cloud-edge-sync-v1.md#m7-multipart-resume)
- [S1-R1–S1-R4 上行收据作用域匹配](../../../../docs/contracts/cloud-edge-sync-v1.md#s1-vectors)

## 第二轮 Verify 后的 W3.1 追溯

[第二轮 Verify](../../../../docs/verification/cloud-edge-sync-contract-reverify.md#第二轮仍待处理) 的 W3 涉及 Q2/Q7、R3/R6 及既有 W1.3。新增 [W3.1](../../../../docs/contracts/cloud-edge-sync-v1.md#w3-vectors)，由 M4.3 验收一次消费、固定顺序的双原因审计、无正常投影及稳定收据，M4.4 复测离线补投的组合条件。[W3 Remediation](../../../../docs/verification/cloud-edge-sync-contract-w3-remediation.md)
