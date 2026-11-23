# 历史问题剩余项复查

日期：2026-11-23。范围：第一轮PR #3整合第二轮PR #4后的代码。此文件是只读复查结果，未实现第三轮业务修改；Owner的生产部署不在本次操作范围。

## 已修复与边界

- BUG-01：main已含HTTP UUID兼容处理，三个前端调用点均有能力缺失的回归。历史线上旧agent.js证据已定位；当前线上部署和缓存状态留给Owner核实，不将GitHub合并等同已部署。
- BUG-02、BUG-03：已验收的商品持久绑定和失败草稿/凭据恢复保留。整合后新增联合路径检查，并运行全部后端143项、前端32项通过。
- OFF-01至OFF-05：第二轮修复保留，24项离线回归通过。单位计算27/16/11元及每杯5.5元；标题实际修改、正文保持、无变化不建新版本、一次性指令不写风格均已验证。
- 没有发现“已保存长期记忆被污染”的证据；此前是候选误分类，不能扩大描述。
- 不能把离线模板的文案质量作为真实模型效果的结论；真实LLM、视觉、线上生产库均未验证。

## 未修改项及代码位置

| 编号/优先级 | 当前行为及影响 | 定位 | 复查方式 |
|---|---|---|---|
| UI-01 / P2 | 用户明确限定商品营销，但快捷文案仍写品牌表达/品牌与商品文案，后端仍支持brand文案。应统一范围后调整入口和路径；本次不擅自删能力 | frontend/src/workbench.js:10及renderContext；backend/app/marketing_agent/contracts.py:36；content.py商品/品牌选择分支 | 代码确认，涉及需求口径差异 |
| UI-02 / P2 | 普通文案齐字段后直接生成，尚未提供用户此前希望的简化需求确认卡 | backend/app/marketing_agent/graph.py:218；frontend/src/agent.js当前仅资料/策略确认 | 隔离流程确认：补齐商品、平台就生成作品，无中间确认事件 |
| UI-03 / P2 | 非选择题只提示在底部聊天回答，题内没有输入框；空点击“提交本组回答”不发送也无缺项提示。另外offer尚未校验时，标签却要求选择已通过成本校验的方案，options为空时没有选项 | frontend/src/agent.js:55、67、153；backend/app/marketing_agent/questions.py:15及pending中的offer分支 | 代码确认；不声称已重新逐项浏览器验收 |
| UI-04 / P2 | v1/v2虽保存为不同artifact，openWork仅发送task_id，workbench只导航任务；生成修改时取最后一个非stale作品。旧版本入口不定位、不切换修改基础 | frontend/src/app.js:266；frontend/src/workbench.js:121；backend/app/marketing_agent/content.py:34 | 隔离流程确认2个作品、不同artifact但同一task；按入口实现均回同一任务 |
| UI-05 / P3 | 查看历史创作草稿读取旧studio draft；Agent通过archive保存到works，未写旧draft。当前入口容易使人误以为作品没保存 | frontend/src/app.js:349、355；backend/app/marketing_agent/archive.py:8 | 隔离流程确认已有2个作品，但旧draft接口payload为null。这是入口适用范围问题，不能记成作品丢失 |
| UI-06 / P3 | 来源引用使用ID截取，product:前缀可能成为“已确认品牌资料·product:”；历史平台直接显示xiaohongshu，时间直接用ISO字符串 | frontend/src/agent.js:28；frontend/src/app.js:265；content.py source_refs | 隔离流程得到source_refs=[product:...]、platform=xiaohongshu；显示规则经代码核对 |

## 验证和排除的误判

临时隔离探针.local-data/audit_remaining.py验证：已归档两个不同版本、两个artifact指向同一任务、旧studio draft仍为空、普通文案没有生成前确认。该探针未改业务代码或用户本地数据库，不纳入永久“断言错误行为”的回归测试。
选项aria-pressed已有对应高亮CSS（agent.css），不将“完全没有选中态”列为代码缺陷。版本和记忆未显示的现象需按数据类型区分；没有证据不写成全部未保存。

## Owner定位点（不操作）

历史BUG-01定位至线上/src/agent.js仍为直接crypto.randomUUID调用；Owner核对运行镜像/源码版本、静态文件挂载、服务路由和缓存，再上线验证发送。本次不登录服务器、不部署、不改缓存，不作当前线上已通过的声明。

## Owner另行处理的发布遗留（只定位，未修改）

1. scripts/make_release_manifest.py:32的tracked_files使用普通git ls-files文本输出，inventory在第44行直接拼路径。当前机器对中文文件名获得Git转义/引号字符串，直接运行--check在读取产品知识库.csv时报OSError，尚未进入漂移判断。属于路径解析依赖Git配置的问题；本次未修改脚本或Git配置。
2. 只读使用git ls-files -z和UTF-8解析重新计算清单后，现有RELEASE_MANIFEST.json与整合代码有漂移：changed=185（包含新增项）、missing=11、extra=77。当前CI未执行这项发布清单校验。Owner应按锁定发布版本处理清单；本次未重写发布清单，更未部署。
3. docs/release-checklist.md仍要求整套pytest单进程混跑，并在日常清单写旧systemd回滚/切换及整套重新导入、重建索引；与AGENTS按模块测试、当前Compose日常更新及仅按实际变更处理索引的口径存在差异。具体看清单A、C、D段及docs/deployment.md。仅列差异交给Owner统一，没有擅自改部署流程。

以上属于发布准备/手册问题，不冒充用户侧业务bug。线上实际运行版本、HTTPS/缓存、备份与回退仍未验证，本次不进入服务器操作。

## 建议第三轮顺序

先统一商品营销范围及普通文案确认，再改提问阶段/空提交反馈，接着解决历史版本定位和旧草稿入口，最后把来源、平台及时间显示改为用户能理解的文字。第三轮实施前按用户约定一次确认大方向，本次只记录问题。
