# ShiftForge — 排班自動化生成模組

規格驅動 (Specification-Driven) 的排班自動化模組。輸入一份人員與需求規格，系統自動完成
策略選擇、排班生成、規則驗證與收斂決策，最終產出一套標準化的交付包。

---

## 給面試受測者

**這是一份面試題。請先閱讀 Wiki，不要只看程式碼。**

| 你該讀的 | 位置 |
|---|---|
| 任務說明（你要做什麼、怎麼交） | [Wiki › Interview Task](../../wiki/Interview-Task) |
| 模組規格書（唯一的正確性判準） | [Wiki › Module Specification](../../wiki/Module-Specification) |
| 架構說明 | [Wiki › Architecture](../../wiki/Architecture) |
| 設定檔 Schema | [Wiki › Configuration Schema](../../wiki/Configuration-Schema) |

**本專案目前無法正確運作。** 你的任務是讓它符合規格書的描述。

> 本題**沒有**提供預期輸出檔（golden file），也**沒有**現成的測試可以告訴你答案。
> 正確與否一律以 **Wiki 的模組規格書**為準。如何確認自己的修正是對的，是這題的一部分。

---

## 環境需求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## 安裝

```bash
uv sync
```

## 執行

```bash
# 產出交付包到 output/
uv run shiftforge examples/clinic_week.json

# 只跑不寫檔，並印出每一輪的決策
uv run shiftforge examples/clinic_week.json --dry-run --verbose

# 指定設定檔目錄與輸出目錄
uv run shiftforge examples/clinic_week.json --config-dir configs --output-dir output
```

程式化介面：

```python
from shiftforge.api import generate_schedule

summary = generate_schedule("examples/clinic_week.json", write_output=False)
print(summary["converged"], summary["hard_violations"])
```

## 離開碼 (Exit Codes)

| 碼 | 意義 |
|---|---|
| `0` | 收斂成功，交付包已產出 |
| `1` | 流程跑完但未收斂 |
| `2` | 輸入規格或設定檔有誤 |

## 專案結構

```
configs/                    三份設定檔（規則 / 策略 / 班別）
examples/                   範例輸入規格
src/shiftforge/
    models.py               共用資料模型
    config.py               設定檔載入
    spec_parser.py          階段 1：規格解析與驗證
    strategies/             策略插件（可抽換）
        base.py             IScheduleStrategy 介面與載入器
        balanced.py         Balanced Rotation
        seniority.py        Seniority First
        coverage.py         Coverage First
    engine.py               階段 2/3/5：策略選擇、生成、收斂決策迴圈
    validator.py            階段 4：規則驗證
    deliverables.py         階段 6：交付包產出
    runner.py               共用編排（兩個入口都走這裡）
    cli.py                  CLI 入口
    api.py                  程式化入口
```

## 開發

```bash
uv run ruff check src
uv run ruff format src
```
