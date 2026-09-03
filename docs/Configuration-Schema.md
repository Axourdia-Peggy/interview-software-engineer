# 設定檔 Schema (Configuration Schema)

本模組有兩類 JSON：**設定檔目錄**（`configs/`，系統層級）與**排班規格**
（`examples/`，使用者層級）。兩者的 `schema_version` 必須一致，
目前支援 **`1.2`**。

---

## 1. `configs/rule_catalog.json` — 規則目錄

排班規則的權威定義。驗證階段逐條執行本目錄宣告的每一條規則。

```jsonc
{
  "schema_version": "1.2",
  "rules": [
    {
      "rule_id": "R001",          // 唯一識別碼
      "name": "coverage",         // 對應到驗證器的實作名稱
      "severity": "hard",         // "hard" | "soft"
      "description": "...",       // 人類可讀的語意說明
      "params": {}                // 該規則的參數，逐規則不同
    }
  ]
}
```

| 欄位 | 型別 | 說明 |
| :-- | :-- | :-- |
| `rule_id` | string | 唯一識別碼，出現在違規訊息中 |
| `name` | string | **驗證器據此找到對應的檢查實作** |
| `severity` | string | `hard` 違反即不可交付；`soft` 僅記錄 |
| `description` | string | 規則語意 |
| `params` | object | 規則參數。**驗證器必須從這裡取值** |

### 各規則的 `params`

| 規則 | 參數 | 意義 |
| :-- | :-- | :-- |
| `coverage` | （無） | — |
| `qualification` | （無） | — |
| `no_double_booking` | （無） | — |
| `rest_between_shifts` | `forbidden_transitions` | 禁止的「前一天→隔天」班別組合 |
| `max_consecutive_days` | `max_days` | 連續上班天數上限 |
| `weekly_hours` | `min_weekly_hours`, `max_weekly_hours` | 總時數的合理區間 |
| `fairness` | `max_spread` | 最忙與最閒者的班數差距上限 |
| `night_shift_quota` | `max_nights` | 計畫期間內的夜班數上限 |

> **注意**：`params` 的鍵名就是契約。
> 驗證器若讀取一個目錄裡不存在的鍵，會落到程式自己的預設值，
> 結果就是**設定檔改了但行為沒變**，而且不會有任何錯誤訊息。

---

## 2. `configs/strategy_catalog.json` — 策略目錄

宣告有哪些排班策略可用，以及它們的載入方式與適用條件。

```jsonc
{
  "schema_version": "1.2",
  "strategies": [
    {
      "strategy_id": "balanced_rotation",
      "display_name": "Balanced Rotation",
      "priority": 1,                    // 數字越小越優先
      "plugin": "shiftforge.strategies.balanced:BalancedRotationStrategy",
      "selection_rules": {
        "max_employees": 40,            // 超過此人數則不適用
        "requires_roles": []            // 需求必須包含這些角色才適用
      },
      "tuning": {                       // 傳給策略的自由參數
        "lookback_days": 3,
        "shuffle_seed": 20260101
      }
    }
  ]
}
```

| 欄位 | 型別 | 說明 |
| :-- | :-- | :-- |
| `strategy_id` | string | 唯一識別碼 |
| `display_name` | string | 顯示名稱 |
| `priority` | int | 嘗試順序，**由小到大** |
| `plugin` | string | `"模組路徑:類別名稱"`，動態匯入用 |
| `selection_rules.max_employees` | int? | 人數上限；超過則此策略不適用 |
| `selection_rules.requires_roles` | string[] | 需求角色須為其超集才適用 |
| `tuning` | object | 策略專屬參數，核心不解讀 |

---

## 3. `configs/shift_types.json` — 班別目錄

```jsonc
{
  "schema_version": "1.2",
  "shift_types": [
    {
      "shift_type_id": "morning",
      "display_name": "Morning",
      "start_hour": 8,
      "end_hour": 16,
      "duration_hours": 8      // 時數計算以此欄為準
    }
  ]
}
```

現有班別：`morning`（08–16）、`evening`（16–24）、`night`（00–08），各 8 小時。

---

## 4. 排班規格 (`examples/*.json`)

使用者的排班需求。

```jsonc
{
  "schema_version": "1.2",
  "project_name": "clinic_week",       // 交付包的資料夾名稱
  "planning_horizon": {
    "start_date": "2026-03-02",        // ISO 日期
    "days": 7                          // 正整數
  },
  "employees": [
    {
      "employee_id": "E01",            // 不得重複
      "name": "Ada",
      "skills": ["nurse", "reception"],// 可勝任的角色
      "seniority": 5,                  // 年資，供 seniority 策略使用
      "max_shifts": 5                  // 此人在計畫期間內的班數上限
    }
  ],
  "demand": [
    {
      "shift_type_id": "morning",      // 必須存在於班別目錄
      "role": "nurse",
      "headcount": 2                   // 正整數；每天都需要這麼多人
    }
  ],
  "unavailability": [                  // 選填
    {"employee_id": "E02", "date": "2026-03-04"}
  ],
  "convergence": {                     // 選填
    "max_iterations": 12,              // 預設 10
    "max_strategy_switches": 2         // 預設 2
  }
}
```

### 驗證規則

解析階段會執行以下檢查，任一項不通過即以離開碼 `2` 中止：

| 檢查 | 錯誤訊息範例 |
| :-- | :-- |
| `schema_version` 相符 | `spec declares schema_version '1.1', this build supports '1.2'` |
| 必填欄位存在 | `spec is missing required field 'demand'` |
| `days` 為正整數 | `planning_horizon.days must be a positive integer` |
| `employee_id` 不重複 | `duplicate employee_id: E01` |
| `shift_type_id` 存在於目錄 | `unknown shift_type_id: afternoon` |
| `headcount` 為正整數 | `demand.headcount must be a positive integer` |
| `unavailability` 的員工存在 | `unavailability cites unknown employee_id: E99` |
| 員工與需求不為空 | `spec declares no employees` |

---

## 附帶的範例

| 檔案 | 特性 |
| :-- | :-- |
| `clinic_week.json` | 10 人、6 座位/天（demand 共 5 列，headcount 合計 2+1+1+1+1）、含不可用日。人力寬裕，第一個策略即可收斂 |
| `ward_tight.json` | 10 人、6 座位/天、含稀缺角色 `senior`。**需要切換策略才能收斂** |
| `pharmacy_relief.json` | 10 人、4 座位/天。人力充裕但工作量分配不均 |

> 三個範例涵蓋不同的收斂路徑，請都執行過一次再判斷是否修好。
