# XIVAPI v2 Specification for Function Calling

This document summarizes the API specification for XIVAPI v2, focusing on the search functionality to support the expansion of AI function calling capabilities.

## Base URL
`https://v2.xivapi.com/api`

## Search Endpoint: `GET /search`

### Parameters
| Parameter | Type | Description |
| :--- | :--- | :--- |
| `sheets` | string | Comma-separated list of sheets to search (e.g., `Item,Action,Recipe`). |
| `query` | string | Data Query Language (DQL) string for filtering and relevance. |
| `limit` | integer | Max number of results to return. |
| `language` | string | Language for field resolution (default: `ja`). Options: `ja`, `en`, `de`, `fr`, `chs`, `cht`, `kr`. |
| `fields` | string | Comma-separated list of fields to include in the response. Use dot notation for nested fields. |
| `transient` | string | Fields from related sheets to include (e.g., `ItemUICategory.Name`). |
| `cursor` | string | Continuation token for pagination. |
| `version` | string | Game version to utilize. |

## Data Query Language (DQL) Syntax

XIVAPI v2 uses a custom query language for the `query` parameter.

| Operator | Description | Example |
| :--- | :--- | :--- |
| `=` | Exact equality | `Name="Excalibur"` |
| `~` | Partial string match (contains) | `Name~"Ironworks"` |
| `>=`, `>`, `<=`, `<` | Numeric comparison | `LevelItem>=600` |
| `+` | MUST match (AND behavior) | `+Name~"Iron" +LevelItem>100` |
| `-` | MUST NOT match (NOT behavior) | `-LevelItem<500` |
| (space) | SHOULD match (OR/Relevance) | `Name~"Iron" Name~"Steel"` |
| `()` | Grouping clauses | `+(Name~"Iron" Name~"Steel")` |
| `.` | Nested field access | `ClassJobCategory.PLD=true` |
| `[]` | Array field access | `BaseParam[].Name="Strength"` |
| `@lang` | Field language decoration | `Name@ja="エクスカリバー"` |

### 🛠️ Important Tips for Japanese Search
- **Use `@ja` decorator**: For searching items/actions by Japanese name, use `Name@ja~"キーワード"` instead of `Name~"キーワード"`.
- **Prefer SHOULD match**: Avoid using `+` prefix for the name query (e.g., `Name@ja~"エーテル"`) to allow more flexible partial matches and better handle variations.

## Recommended Sheets & Key Fields

### 1. Item (アイテム)
- **Sheet**: `Item`
- **Key Fields**: `Name`, `Name@ja`, `Description`, `Description@ja`, `LevelItem.value`, `ItemUICategory.Name`
- **Notes**: Item descriptions are generally available via `/search` by requesting `Description`.

### 2. Action (アクション/スキル)
- **Sheet**: `Action`
- **Key Fields**: `Name`, `Name@ja`, `ClassJobLevel`, `ClassJob.Abbreviation`, `ActionCategory.Name`
- **⚠️ Description Issue**: Descriptions for actions are often stored in `ActionTransient` and are **NOT** reliably returned by the `/search` endpoint even with `fields=*`.
- **Solution**: To get the description, first search via `/search`, then fetch the specific row using `/sheet/Action/{id}`. The description will be under `transient.Description` in the row result.

### 3. Recipe (製作レシピ)
- **Sheet**: `Recipe`
- **Key Fields**: `ItemResult.Name`, `CraftType.Name`, `RecipeLevelTable.ClassJobLevel`, `AmountResult`, `Ingredient`, `AmountIngredient`
- **Ingredients Data**:
    - `Ingredient`: Array of item objects. Only entries with `value > 0` are valid.
    - `AmountIngredient`: Array of integers representing the count for each item in `Ingredient`.
    - Both arrays correspond by index.

### 4. Quest (クエスト)
- **Sheet**: `Quest`
- **Key Fields**: `Name`, `Levelmain`, `ClassJobCategory.Name`

### 5. Achievement (アチーブメント)
- **Sheet**: `Achievement`
- **Key Fields**: `Name`, `Description`, `Points`, `AchievementCategory.Name`

### 6. Others
- **FATE**: `Fate`
- **Mount**: `Mount`
- **Minion**: `Companion` (Note: internal name is `Companion`)
- **Status (Buff/Debuff)**: `Status`

## Notes
- **Player/Character Search**: XIVAPI v2 focuses on game client data and **does not support** server-side player or free company search.
- **Sorting**: v2 does not have an explicit `sort` parameter. Results are sorted by relevance (`score`).
- **Timeout**: Requests involving detailed row fetches or large sheets (like Recipe) should have a timeout of at least **30 seconds**.
- **Fields**: Use `fields=*` carefully. While it ensures all data is retrieved, it can result in large response payloads.
