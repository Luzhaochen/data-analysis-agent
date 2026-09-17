# categories 品类维度表

- 用途：品类名称与层级关系；回答「按品类下钻/上卷」类问题时的维度翻译表
- 粒度：一行 = 一个品类（一级或二级混存，见坑 1）；唯一键 category_id；与 products/traffic 是 1:N
- 时间字段：无（纯维度表，不随时间变化；时间过滤一律在事实表 orders/order_items/traffic 侧做）
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
| category_id | INT | 品类ID | 唯一（自增） | 事实表挂的关联键 |
| category_name | VARCHAR(64) | 品类名称 | 一级与二级共用同一列 | 直接按名称分组会把两层混在一起（见坑 3） |
| parent_id | INT | 父品类ID | **NULL = 一级品类**；非 NULL = 所属一级品类ID | 上卷键（见坑 2） |
| category_level | TINYINT | 层级 | 1=一级品类 2=二级品类（本库：3 个一级 + 10 个二级） | 写查询必带的分层条件 |

- 指标口径：
  - 本表无指标（纯维度表）——金额/数量指标全部在事实表侧（orders/order_items/traffic），
    本表只做维度翻译、下钻与上卷，禁止在本表上做 COUNT/SUM 当业务指标
- 注意事项/坑：
  - 一级与二级品类**混存在同一张表** → 涉及品类的查询必须先按 category_level 分层
    （或 parent_id IS NULL），否则「按品类汇总」会把层级混在一组
  - products 与 traffic 挂的是**二级品类**（products.category_id 为二级品类ID）
    → 指标天然落在二级；要一级口径必须经 parent_id 上卷，不能直接取 category_level=1 的行 JOIN
  - 按 category_name 分组会把一级/二级名字混在一起 → 分组一律用 category_id，
    名称用 JOIN 带回（维度表只做翻译，不做分组依据）
  - 跨一级品类的订单在品类订单量中会重复计数 → **各品类订单量不可跨品类求和**；
    GMV 按明细归属是拆分口径，订单量按品类归属只是「品类视角」（上卷分析通用约定）
- 常用过滤：
  - `category_level = 2`（二级品类——与事实表一致的粒度）
  - `category_level = 1`（只看一级品类）
  - `parent_id = <一级ID>`（某个一级品类下的全部二级）
- 关联键：
  - category_id → products.category_id（1:N，商品挂在二级品类上）
  - category_id → traffic.category_id（1:N，流量一行一天一二级品类）
  - parent_id → categories.category_id（自关联上卷：二级 → 所属一级）
