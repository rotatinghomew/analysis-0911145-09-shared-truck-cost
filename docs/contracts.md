# 产品数据与调用约定

成员是合作社而非订单。members 含箱数、重量、线路和 incompatible；fleet 为离散车型，tariffs 中 eligible_green 的减免只有满足整车合法装载约定时生效。现有 quote(subset) 返回该子联盟可达的最小运输成本及装载见证，金额均为整数分。POST /allocation {case, scenario?} 已实现，返回 {snapshot, scenario, feasible, total_cost, allocations, blocking, gains, sensitivity, diagnostics}。每种分法必须守恒，稳定指任一可行子联盟所分摊合计不高于独立合作成本；不稳定时要展示证据，不能把公平性指标替代稳定证明。可允许补贴，但须显式单列来源。

当前 GET /cases、POST /preview、POST /allocation 和 GET /health 已可用；client.analysis(base, case, scenario=...) 是该分析的业务消费调用。原始数据通过 app.store 读取，snapshot 为输入字节的 SHA-256。接口保留 JSON 有限数值约定（allow_nan=false），所有对外金额均为整数分，分数解仅作为 fractional_cents 参考并标注四位小数。

分析口径：app/allocation.py 以 quote 为成本神谕枚举全部 2^n 个子联盟，构成离散成本博弈。allocations 并列给出四种分法——nucleolus（顺序 LP 核仁，再以混合整数规划取整到整分并保持在整数最小核内）、shapley（Shapley 值后按 L1 最优取整）、box_proportional（按箱数比例，代表大户主张）、equal_savings（均分合作节约）；空核时追加 nucleolus_with_minimum_subsidy 并给 subsidy_cents 与 subsidy_source。每种分法都对全部可行子联盟重新核验稳定结论，blocking_coalitions 附该子联盟独立运输的 loads_witness 作为退出证据，不靠连续吨公里单价外推。blocking.core_status 为 nonempty/empty/undefined_infeasible_grand_coalition；fractional_epsilon_cents 与 integer_epsilon_cents 分别是分数与整分最小核让步，空核时 diagnostics 列出在最大让步上绑定的成员组合及恢复稳定所需的最小外部补贴。

allocations 中每项含 name、cents（成员到整数分的映射）、fractional_cents、stable、worst_violation_cents、blocking_coalitions 和可选 subsidy_cents。守恒为成员合计加外部补贴等于 total_cost。成本不可行时 feasible=false、total_cost=null、allocations=[]，blocking 给出最小不可行成员组合与最大可行组合，diagnostics 说明需求或车辆约束，不输出虚构分法。gains 列出各自单干合计、联盟总成本、总节约与节约率、各成员边际贡献和每个有节约的子联盟明细。sensitivity 对基线与 scenarios 中每个需求/车辆情景用完全相同的方法重算，便于同一口径比较各方负担。green_min_fill 是该模拟合同条件，不用于解释真实交通法规。
