# 架構說明 (Architecture)

本頁說明程式碼的組織方式與各模組的職責邊界。
關於**正確行為**的定義請見[模組規格書](Module-Specification.md)。

---

## 分層概觀

```
                        ┌──────────────┐   ┌──────────────┐
   入口層 (Frontend)    │   cli.py     │   │   api.py     │
                        └──────┬───────┘   └──────┬───────┘
                               └─────────┬────────┘
                                         v
   編排層 (Orchestration)          ┌──────────────┐
                                   │  runner.py   │
                                   └──────┬───────┘
                                          v
                        ┌─────────────────────────────────┐
   流程層 (Pipeline)    │ spec_parser → engine → validator │
                        │                    → deliverables│
                        └────────────┬────────────────────┘
                                     v
                        ┌─────────────────────────────────┐
   插件層 (Plugins)     │  strategies/ (IScheduleStrategy) │
                        └─────────────────────────────────┘
                                     v
                        ┌─────────────────────────────────┐
   資料層 (Data)        │   models.py  +  config.py        │
                        └─────────────────────────────────┘
                                     ^
                        ┌─────────────────────────────────┐
   設定層 (Config)      │        configs/*.json            │
                        └─────────────────────────────────┘
```

---

## 各模組職責

| 模組 | 職責 | 不該做的事 |
| :-- | :-- | :-- |
| `models.py` | 共用資料模型（dataclass） | 任何 I/O |
| `config.py` | 載入三份設定檔為不可變的 `CatalogBundle` | 決定業務邏輯 |
| `spec_parser.py` | 階段 1：解析並驗證使用者規格，並展開座位 | 決定誰排哪一班 |
| `strategies/` | 由 engine 在階段 3 呼叫：把人指派到座位 | 決定何時重試或換策略 |
| `validator.py` | 階段 4：對照規則目錄檢查班表 | 修改班表 |
| `engine.py` | 階段 2/3/5：策略選擇、產生、收斂決策迴圈 | 直接指派人員 |
| `deliverables.py` | 階段 6：序列化交付包 | 改變任何判定結果 |
| `runner.py` | 串接上述階段的唯一編排點 | 提供入口專屬邏輯 |
| `cli.py` / `api.py` | 參數解析與結果呈現 | 各自實作業務邏輯 |

---

## 關鍵設計原則

### 1. 設定檔是權威 (Config is Authoritative)

`configs/` 底下的三份 JSON 是規則、策略與班別的**單一事實來源**。

> 程式碼不得內建任何已經寫在設定檔裡的數值。
> 設定檔改了，行為就必須跟著改——否則兩邊會悄悄分歧，
> 而且**不會有任何錯誤訊息**。

### 2. 插件式策略 (Pluggable Strategies)

新增一種排班策略的完整步驟：

1. 在 `strategies/` 新增一個模組，實作 `IScheduleStrategy.build()`
2. 在 `configs/strategy_catalog.json` 新增一筆 entry，`plugin` 欄位填
   `"module.path:ClassName"`

**核心程式碼一行都不需要改。** `strategies/base.py` 的 `load_strategy()`
以動態匯入完成掛載。

### 3. 硬規則由建構時保證 (Hard Rules by Construction)

策略在指派前必須呼叫 `IScheduleStrategy.eligible()` 這個資格閘門。
其用意是讓候選班表**不可能**在建構階段就違反硬規則——
驗證器是最後一道防線，不是唯一一道。

若某個座位找不到任何合格人選，策略應把它放進 `roster.unfilled`，
而不是硬塞一個不合格的人。

### 4. 單一編排點 (Single Orchestration Point)

`cli.py` 與 `api.py` 都必須經過 `runner.run_project()`。
兩個入口若各自實作流程，就會產生行為分歧。

### 5. 失敗要大聲 (Fail Loudly)

規格或設定有問題時，流程必須中止並回報，不得以預設值悄悄帶過。
一個被靜默略過的檢查，會讓不合規的產出看起來像是合格的。

---

## 資料流

```
examples/*.json ──┐
                  ├──> parse_spec() ──> ScheduleSpec ──> expand_slots() ──> [Slot]
configs/*.json ───┘                          │                                │
                                             v                                v
                                    select_strategies()              strategy.build()
                                             │                                │
                                             └──────────> StrategyContext ────┘
                                                                              │
                                                                              v
                                                                          Roster
                                                                              │
                                                                              v
                                                                        validate()
                                                                              │
                                                                              v
                                                                    ValidationReport
                                                                              │
                                                    ┌─────────────────────────┤
                                                    v                         v
                                            [收斂] write_package()    [未收斂] 決策迴圈
```

---

## 重要型別

| 型別 | 說明 |
| :-- | :-- |
| `ScheduleSpec` | 解析並正規化後的使用者需求 |
| `Slot` | 一個待填的座位，由 `(day, shift_type_id, role, seat)` 唯一識別（欄位名是 `day`；輸出層的 CSV 欄名與 JSON 鍵才叫 `date`） |
| `Assignment` | 一個 Slot 與一位員工的綁定 |
| `Roster` | 一份候選班表（`assignments` + `unfilled`） |
| `Violation` | 一條違規紀錄（規則 ID、名稱、嚴重度、訊息） |
| `ValidationReport` | 一次驗證的完整結果；`passed` 的定義是「無 hard 違規」 |
| `StrategyContext` | 策略可見的所有資訊，含 `pressure` |
| `RunResult` | 一趟迴圈的結果，含逐輪決策紀錄 `history` |

---

## 執行流程追蹤

想觀察決策迴圈的實際行為，加上 `--verbose`：

```bash
uv run shiftforge examples/ward_tight.json --dry-run --verbose
```

輸出每一輪的策略、壓力值、違規數與所做的決策，是理解迴圈行為最快的方式。
