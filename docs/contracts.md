# 产品数据与调用约定

成员是合作社而非订单。members 含箱数、重量、线路和 incompatible；fleet 为离散车型，tariffs 中 eligible_green 的减免只有满足整车合法装载约定时生效。现有 quote(subset) 返回该子联盟可达的最小运输成本及装载见证，金额均为整数分。新增 POST /allocation {case, scenario?} 返回 {snapshot, total_cost, allocations, blocking, sensitivity, diagnostics}。每种分法必须守恒，稳定指任一可行子联盟所分摊合计不高于独立合作成本；不稳定时要展示证据，不能把公平性指标替代稳定证明。可允许补贴，但须显式单列来源。

当前 GET /cases、POST /preview 和 GET /health 已可用；client.analysis 是待接入的业务消费调用，新分析路由尚不存在。原始数据通过 app.store 读取，snapshot 为输入字节的 SHA-256。新增接口须保留现有预览能力和 JSON 有限数值约定。

allocations 中每项含 name、cents（成员到整数分的映射）和可选 subsidy_cents。守恒为成员合计加外部补贴等于 total_cost。成本不可行时 total_cost=null，并说明需求或车辆约束，不输出虚构分法。green_min_fill 是该模拟合同条件，不用于解释真实交通法规。
