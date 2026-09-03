# 排班自動化生成模組 (Shift Schedule Generation Automation Module)

> 本頁是本專案**唯一的正確性判準**。程式碼的行為若與本頁不符，以本頁為準。

## 概述 (Overview)

此核心模組旨在實現規格驅動 (Specification-Driven) 的排班自動化。模組接收使用者定義的
人員資料、班別需求與排班規則，透過內建的 Strategy Selection Agent 自動完成排班策略的
選擇、Schedule Generation Agent 完成班表生成、以及規則驗證與收斂決策
(Rule Validation & Convergence Decision)，最終生成一套完整、標準化、可交付給現場主管
使用的交付包 (Handoff Package)。

模組採插件式架構，新增一種排班策略只需實作 `IScheduleStrategy` 介面並登錄至設定檔，
核心流程不需修改。

---

## 開發總體藍圖 (Overall Development Roadmap)

- **階段一：基礎流程自動化 (Foundation & Automation)**
  - 目標：建立 `規格 → 策略選擇 → 生成 → 驗證 → 收斂 → 交付` 的端到端自動化骨架。
  - 已完成能力：
    - 規格解析與參照完整性檢查
    - 三種 Rule-Based 排班策略（插件式）
    - 硬規則 / 軟規則雙層驗證
    - 收斂決策迴圈與交付包產出

- **階段二：規則庫擴充 (Rule Catalog Expansion)**
  - 目標：規則以設定檔宣告式描述，新增規則不需改動核心流程控制邏輯。
  - 前置條件：階段一的規則驗證框架。

- **階段三：多入口一致性 (Multi-Frontend Consistency)**
  - 目標：CLI 與程式化 API 兩種入口在相同輸入下產生完全一致的結果。
  - 前置條件：共用編排層 (`runner`) 已建立。

- **階段四：AI 輔助策略 (AI-Enhanced Strategy)** `[Idea]`
  - 目標：引入 AI-Based Strategy Agent，以歷史排班資料學習偏好並加速收斂。
  - 前置條件：階段一的插件式 Agent 框架。

---

## 持續性工程軌道：節點可替換性 (Node Replaceability)

本模組的各節點透過統一介面與核心流程溝通，可獨立替換而不影響其他節點。

| 節點類型 | 職責 | 已支援 | 規劃中 |
| :-- | :-- | :-- | :-- |
| Spec Parser | 規格解析與驗證 | JSON | YAML |
| Strategy Plugin | 排班策略 | Balanced / Seniority / Coverage | AI-Based |
| Rule Engine | 規則驗證 | 設定檔宣告式規則 | 自訂規則腳本 |
| Deliverable Writer | 交付包序列化 | CSV / JSON / TXT | Excel |
| 入口 (Frontend) | 使用者介面 | CLI、程式化 API | GUI |

---

## 模組架構與設計流程 (Module Architecture & Design Flow)

### Agent 架構總覽

```
                Schedule Specification (排班規格)
                             |
                             v
        ┌────────────────────────────────────────────┐
        │        Strategy Selection Agent            │
        │   依 selection_rules 篩選 → 依 priority 排序 │
        └─────────────────────┬──────────────────────┘
                              │ 選定的策略 (依序)
                              v
        ┌────────────────────────────────────────────┐
        │       Schedule Generation Agent            │
        │        (IScheduleStrategy 插件)             │
        └─────────────────────┬──────────────────────┘
                              │ 候選班表 (Candidate Roster)
                              v
        ┌────────────────────────────────────────────┐
        │          Rule Validation                   │
        │      硬規則 (hard) / 軟規則 (soft)          │
        └─────────────────────┬──────────────────────┘
                              │ 違規清單 + Pass/Fail
                              v
        ┌────────────────────────────────────────────┐
        │     Convergence Check & Decision Loop      │
        │                                            │
        │  [成功]           → Handoff Package        │
        │  [失敗 → 加壓]    → 同策略重試             │
        │  [失敗 → 換策略]  → 下一個候選策略         │
        └────────────────────────────────────────────┘
```

### Strategy Selection Agent (策略選擇代理)

依排班規格從策略目錄中篩選出適用的策略，並依 `priority` 由小到大排序。

- 輸入：Schedule Specification + 策略目錄 (`strategy_catalog.json`)
- 輸出：適用策略的有序清單
- 篩選條件：`selection_rules`（如 `max_employees`、`requires_roles`）
- 若無任何策略適用，視為設定錯誤，流程中止

### Schedule Generation Agent (班表生成代理)

將人員指派到每一個排班座位 (Slot)。

| 種類 | 方法 |
| :-- | :-- |
| Balanced Rotation | 優先指派目前工作量最少的人，平均分攤 |
| Seniority First | 優先指派年資最高的人；加壓後逐步忽略年資 |
| Coverage First | 依角色稀缺度排序座位，先填最難填的座位 |

- 輸入：座位清單 + Schedule Specification + 策略參數 (`tuning`) + 壓力值 (`pressure`)
- 輸出：候選班表 (Roster) + 未能填滿的座位清單 (unfilled)
- **硬性要求**：策略在指派前必須通過資格檢查閘門，候選班表不得在建構時就違反硬規則

### 壓力機制 (Pressure)

`pressure` 由決策迴圈在同一策略內每次重試時遞增，起始為 0。策略應隨壓力升高
逐步放寬**自身的偏好排序**，但**永遠不得違反硬規則**。

---

## 設計迴圈流程 (Design Loop Flow)

### 1. 規格解析與驗證 (Specification Parsing & Validation)

- **目標**：確立排班目標，確認規格可被後續階段執行。
- **方法**：解析規格文件，並執行下列檢查。任一項不通過即中止流程（fail-fast），
  不得產出半合法的規格物件：
  - `schema_version` 必須與本版支援的版本相符
  - 必填欄位存在（`project_name`、`planning_horizon`、`employees`、`demand`）
  - `planning_horizon.days` 為正整數
  - `employee_id` 不得重複
  - `demand` 引用的 `shift_type_id` 必須存在於班別目錄（參照完整性）
  - `demand.headcount` 為正整數
  - `unavailability` 引用的 `employee_id` 必須存在
  - `employees` 與 `demand` 不得為空

### 2. 座位展開 (Slot Expansion)

- **目標**：把需求表展開為每一個待填的具體座位。
- **方法**：`計畫期間內的每一天 × demand 的每一列 × headcount` 產生一個 Slot。
  每個 Slot 由 `(day, shift_type_id, role, seat)` 唯一識別（dataclass 欄位名為 `day`；輸出層的 CSV 欄名與 JSON 鍵才是 `date`）。

> 例：7 天 × (morning/nurse 2 人 + morning/reception 1 人) = 21 個座位。

### 3. 策略選擇 (Strategy Selection)

- **目標**：決定要依序嘗試哪些策略。
- **方法**：見上述 Strategy Selection Agent。

### 4. 班表生成 (Schedule Generation)

- **目標**：產生候選班表。
- **方法**：見上述 Schedule Generation Agent。

### 5. 規則驗證 (Rule Validation)

- **目標**：判斷候選班表是否可交付。
- **方法**：對規則目錄中**每一條**規則執行檢查，蒐集所有違規項。

  - **規則目錄中宣告的每一條規則都必須被實際執行。** 若有規則無法執行
    （例如缺少對應實作），此為系統錯誤，流程必須中止並回報，
    **不得靜默略過**——被略過的規則會讓不合規的班表通過驗證。
  - 規則的參數一律由規則目錄提供。**程式不得自行內建與目錄重複的數值**；
    目錄改了值，驗證行為就必須跟著改。

- **嚴重度 (severity)**：
  - `hard`：違反即不可交付
  - `soft`：違反仍可交付，但必須記錄於驗證報告中

### 6. 收斂檢查與決策迴圈 (Convergence Check & Decision Loop)

- **目標**：判斷排班是否完成，或決定下一步。
- **方法**：將驗證結果與收斂條件比對，執行以下決策：

  - **[成功]** 若無任何 `hard` 違規，判定收斂，進入交付階段。
    `soft` 違規不阻擋交付。
  - **[失敗 → 加壓]** 若仍有 `hard` 違規，但當前策略尚有重試額度，
    且判斷提高壓力仍有幫助，則 `pressure + 1` 後以同一策略重試。
  - **[失敗 → 換策略]** 若當前策略已用盡重試額度，或判斷提高壓力無助於改善，
    則換用下一個候選策略，`pressure` 歸零重新開始。

- **收斂上限**：
  - `max_iterations`：整趟流程的生成次數上限。
  - `max_strategy_switches`：允許**切換策略**的次數上限。
    此為「切換」次數，非「策略」數量——允許 N 次切換，代表最多可嘗試 N + 1 個策略。
  - 每個策略分得的重試額度為 `max_iterations // 策略數量`（至少為 1）。

- **未收斂的處理**：流程結束仍未收斂時，仍須輸出交付包，內容為過程中
  **違規最少**的那份候選班表，並在驗證報告中如實標示為未通過。

---

## 規則定義 (Rule Definitions)

規則的權威定義位於 `configs/rule_catalog.json`。下表說明各規則的語意。

| ID | 名稱 | 嚴重度 | 語意 |
| :-- | :-- | :-- | :-- |
| R001 | `coverage` | hard | 需求表宣告的每個座位都必須恰好被指派一次；不得遺漏，也不得重複指派 |
| R002 | `qualification` | hard | 員工只能被指派到其 `skills` 清單內的角色 |
| R003 | `no_double_booking` | hard | 同一員工同一日曆日最多只能有一個指派 |
| R004 | `rest_between_shifts` | hard | 夜班之後的隔天不得緊接早班 |
| R005 | `max_consecutive_days` | hard | 連續上班天數不得超過 `max_days` |
| R006 | `weekly_hours` | soft | 每位員工的總時數應落在 `[min_weekly_hours, max_weekly_hours]` 區間內 |
| R007 | `fairness` | soft | 班數最多與最少的員工，其差距不應超過 `max_spread` |
| R008 | `night_shift_quota` | soft | 每位員工在整個計畫期間內的夜班數不應超過 `max_nights` |

**不可用性 (unavailability)**：規格中列出的 `(employee_id, date)` 組合代表該員工
當日無法排班。此為硬性限制，等同於資格不符。

---

## 產品介面與交付物 (Product Interface & Deliverables)

### 輸入介面 (Input)

系統支援 **CLI**（適合批次處理）與**程式化 API**（適合嵌入其他系統）兩種入口。

> **兩個入口在相同輸入下必須產生完全一致的結果。**
> 任一入口自行決定的行為，都是兩者可能產生分歧的地方。

### 最終交付物 (Output)

執行完畢後產出標準化交付包，位於 `<output_dir>/<project_name>/`：

| 檔案 | 內容 |
| :-- | :-- |
| `roster.csv` | 班表，一列一個指派，欄位為 `date, shift_type, role, seat, employee_id, employee_name` |
| `roster.json` | 結構化班表，含每位員工的總時數與未填滿座位清單 |
| `validation.txt` | 驗證結果：`verdict`、硬/軟違規數量、逐條違規訊息 |
| `run_summary.json` | 決策迴圈的完整紀錄：每一輪的策略、壓力值、違規數與所做決策 |

**未收斂時交付包仍須產出**，`validation.txt` 的 `verdict` 標示為 `FAIL`。

### 離開碼 (Exit Codes)

| 碼 | 意義 |
| :-- | :-- |
| `0` | 收斂成功 |
| `1` | 流程完成但未收斂 |
| `2` | 輸入規格或設定檔有誤 |

---

## 狀態表 (Status Table)

### 階段 (Stages)

| 階段 | 目標 | 狀態 |
| :-- | :-- | :-- |
| 階段一 基礎流程自動化 | 端到端骨架 | Ready |
| 階段二 規則庫擴充 | 宣告式規則 | Optimize |
| 階段三 多入口一致性 | CLI / API 行為一致 | Optimize |
| 階段四 AI 輔助策略 | AI-Based Strategy Agent | Idea |

### Agent

| Agent | 實作 | 狀態 |
| :-- | :-- | :-- |
| Strategy Selection Agent | Rule-Based | Ready |
| Schedule Generation Agent | Balanced Rotation | Ready |
| Schedule Generation Agent | Seniority First | Ready |
| Schedule Generation Agent | Coverage First | Ready |
| Schedule Generation Agent | AI-Based | Idea |

### 功能 / 流程步驟

| 功能 | 說明 | 狀態 |
| :-- | :-- | :-- |
| 規格解析與驗證 | 參照完整性 + fail-fast | Ready |
| 座位展開 | 需求表 × 日曆 | Ready |
| 策略選擇 | selection_rules 篩選 + priority 排序 | Ready |
| 班表生成 | 三種 Rule-Based 策略 | Ready |
| 規則驗證 · 硬規則 | R001–R005 | Ready |
| 規則驗證 · 軟規則 | R006–R008 | Optimize |
| 收斂迴圈 · 失敗→加壓 | 同策略重試 | Ready |
| 收斂迴圈 · 失敗→換策略 | 下一個候選策略 | Ready |
| 交付 · roster / validation / summary | 交付包產出 | Ready |
| 多入口一致性 | CLI 與 API | Optimize |
| 自訂規則腳本 | 使用者自行擴充規則 | Idea |

### 狀態定義

| 狀態 | 意義 |
| :-- | :-- |
| Ready | 已完成並穩定 |
| Optimize | 可運作，仍在優化 |
| Idle | 已規劃，尚未啟動 |
| Idea | 構想階段，尚無實作 |
