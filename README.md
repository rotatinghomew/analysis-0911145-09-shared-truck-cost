# 拼车规模收益与成员退出约束下的运费分担分析

这是一个本地运行的分析工作台。当前版本提供业务数据检查、已有口径的预览、HTTP 查询及 Python 消费端；新的分析入口尚待接入。字段的业务含义与兼容边界见 `docs/contracts.md`，验证范围见 `docs/verification.md`。

数据均为本地合成，不含真实姓名、电话号码或生产系统凭据。`standard` 是常规资料，`edge` 用于检查信息不足或约束冲突。它们只描述观测，不预设分析结论。

## 本地使用

Python 3.11，依赖版本固定在 `requirements.txt`。NumPy/SciPy 是分析工作台的数值工具；预览逻辑主要使用标准库。准备阶段安装依赖，仓库不在启动或测试时下载任何资源。

支持 Python 3.11 系列的补丁版本；Docker 基础镜像通过 SHA256 固定为 Python 3.11.14，依赖清单保持精确版本。相同依赖还需在非 root 的 Python 3.11.2 Linux 环境中验证，应用不依赖特定补丁版本。

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m app.demo
python -m app.server
```

服务监听 `127.0.0.1:8080`，也可通过 `PORT` 调整。预览请求由 `app/client.py` 发起；`app.demo` 在临时端口启动真实服务并完整打印现有业务输出与新的分担分析（基线及每个需求/车辆情景），不是录制日志的回放。服务接口和数据文件的可见性约定不能互相替代。

## 运费分担分析

`POST /allocation` 的请求体为 `{"case": "standard", "scenario": "a-expands"}`，`scenario` 可省略。分析把 `quote` 对全部成员组合核算出的离散运输成本视为合作博弈的特征函数，不做连续吨公里平滑：整车门槛导致的绿通减免、线路隔离、互斥成员都原样进入每个子联盟的成本。

返回中 `allocations` 并列核仁、Shapley、按箱比例、均分节约四种分法，各自带整数分账单、分数参考值和对全部可行子联盟重新核验的稳定结论；被阻挡时 `blocking_coalitions` 给出该组合独立成行的装载见证。`blocking` 标明核是否非空、分数与整分最小核让步；空核时追加显式标注来源的最小补贴方案和在最大让步上绑定的冲突组合，而不是输出一组号称公平的金额。`gains` 列规模收益（单干合计、联盟成本、节约率、边际贡献、子联盟节约明细），`sensitivity` 在基线与各情景间保持同一方法口径，不可行大联盟只给冲突组合说明、不虚构分法。

## 可复现环境

```sh
docker build -t local/shared-truck-cost:baseline .
docker run --rm --network none local/shared-truck-cost:baseline python -m unittest discover -s tests -v
docker run --rm --network none local/shared-truck-cost:baseline
```

准备阶段允许构建镜像和预装依赖；正式演示不进行构建或安装。默认演示只显示已有功能。新能力完成后，请使演示通过实际 HTTP 消费调用展示输入口径、分析结果和限制，保留完整输出；小样本预期在 90 秒内结束。功能测试启用方式：`RUN_ACCEPTANCE=1 python -m unittest tests.test_acceptance -v`，默认跳过这些依赖新接口的契约测试。
