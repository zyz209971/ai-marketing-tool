# Research

Decision: 在对话创建时绑定SKU，不用文字匹配维持关联。Rationale: 现有Brief和持久化足够，修改文字和刷新不会失去身份。Alternatives: 只扩展sessionStorage仍在首次发送前显示待确定，服务端状态无法作为唯一依据，故不选。多商品需重构单SKU编排，本轮明确拒绝而非伪支持。

依据：已读取现有前端创建/发送路径、CreateConversation、store.create_task及enqueue去重顺序。没有外部资料研究或模型实验的未知依赖，未启动研究代理。
