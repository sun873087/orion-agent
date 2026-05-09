# Dark Theme 修正完工記錄

**完成日期**:2026-05-10
**前置 phase**:`phase-WEB-UI-completion.md` (Stage 3 三欄佈局)
**狀態**:✅ 程式碼就緒;`npm install && npm run build` 已重新編譯 dist。
切到 dark mode 後整體配色對齊 Claude.ai 暗模式。

> 本檔記錄「使用者切換暗模式但畫面看起來仍像 light」這個 bug 的根因與修法。

---

## 問題

使用者在 SettingsModal → Appearance 切到 **Dark**,但結果像下圖:

- 主背景仍是奶油色 `#FAF9F5`(看起來幾乎全白)
- 文字非常淡,對比差
- 與 Claude.ai 真正的暗模式(深黑底 `#1A1A18` + 純奶油白文字)落差大

Theme toggle 機制本身是 work 的(`<html class="dark">` 確實有套上),但畫面沒變暗。

## 根因

`index.css` 的 `:root` / `.dark` CSS variables **是 theme-aware 的**,Tailwind config 也把 `bg-claude-cream`、`text-claude-text` 等 token 綁到 var。問題出在:

**幾乎每個元件的「卡片 / 輸入框 / dropdown / Modal 內容」都用了 hardcode 的 `bg-white`**:

| 檔案 | 行 | 元素 |
| --- | --- | --- |
| `InputBox.tsx` | 103 | 主輸入框 wrapper |
| `Login.tsx` | 70, 75, 85, 99, 116 | 登入卡片 / tab toggle / username & password input |
| `ModelPicker.tsx` | 55, 80 | Model 按鈕 + dropdown |
| `WorkspaceFiles.tsx` | 62 | 檔案 dropdown |
| `CustomInstructionsPanel.tsx` | 89, 105 | About you / This conversation textarea |
| `SettingsPanel.tsx` | 136 | Stored values 列表項 |
| `MessageList.tsx` | 146 | Scroll-to-bottom 浮動按鈕 |
| `PermissionDialog.tsx` | 41, 52, 64, 70, 76 | code chip / tool input box / 4 個按鈕 |

`bg-white` 在 Tailwind 中是個固定 token,**不會隨 `dark` class 變色**。所以即使 `.dark` 把 `--c-cream` 改成 `#1A1A18`,輸入框、dropdown、Login 卡片等元素仍是純白,把整個畫面拉成「白底 + 黑文字被淡化」的怪樣子。

附帶的問題:

1. `shadow-soft` / `shadow-input` / `shadow-modal` 用 `rgba(0,0,0,0.04~0.15)` 黑色透明,在 dark 模式下完全看不到 → 卡片邊界消失
2. `text-red-700` / `bg-red-50` / `border-red-100`(error 訊息)在深色背景對比過低,字幾乎看不見
3. `text-emerald-700`(saved 提示)同樣對比差

---

## 修法

### 1. 校準 dark CSS variables 對齊 Claude.ai

`frontend/src/index.css`:

```css
.dark {
  --c-cream: 26 26 24;          /* #1A1A18 — 主背景,接近全黑 */
  --c-panel: 38 38 36;          /* #262624 — sidebar / 卡片 / 輸入框 */
  --c-border: 64 64 60;         /* #40403C — 卡片邊界,在深色上要更亮才看得到 */
  --c-border-soft: 48 48 44;    /* #30302C */
  --c-text: 250 249 245;        /* #FAF9F5 — 純奶油白(原本 235 233 226 偏暗) */
  --c-text-dim: 184 181 173;
  --c-text-faint: 132 129 122;
  /* orange / code / scrollbar 維持 */
}
```

關鍵是 `--c-text` 改成 `250 249 245`,也就是 light mode 的 cream 值,讓主文字達到 Claude.ai 的純奶油白。

### 2. 全域 `bg-white` → `bg-white dark:bg-claude-panel`

採 Tailwind dark variant 而非改 token 語意,理由:

- `bg-white` 在 light mode **應該維持純白**(輸入框與 cream 主背景要有對比)
- 改成 `bg-claude-panel` 會讓 light mode 變成淡奶油色,毀掉原本的 light layout
- dark variant 是最小侵入 — 只在 `<html class="dark">` 時套用

範例(InputBox.tsx):

```tsx
className={`relative rounded-2xl
  bg-white dark:bg-claude-panel
  shadow-input dark:shadow-none dark:ring-1 dark:ring-claude-border
  transition-shadow ...`}
```

### 3. shadow 在 dark mode 用 ring 替代

黑色 shadow 在深底上沒效果。對「需要邊界可見」的元素(輸入框、Login 卡片、Login tab toggle):

```tsx
shadow-soft dark:shadow-none dark:ring-1 dark:ring-claude-border
```

對 dropdown / floating(ModelPicker dropdown / WorkspaceFiles dropdown / scroll-to-bottom 按鈕)用更深的 shadow:

```tsx
shadow-modal dark:shadow-[0_25px_50px_-12px_rgba(0,0,0,0.6)]
```

### 4. Error / success 文字加 dark variant

統一規則:

| 原 light | dark variant |
| --- | --- |
| `text-red-700` | `dark:text-red-300` |
| `bg-red-50` | `dark:bg-red-950/40` |
| `border-red-100` / `border-red-200` | `dark:border-red-900/60` |
| `text-emerald-700` | `dark:text-emerald-400` |

涵蓋:Login error、InputBox error、CustomInstructionsPanel error/saved、SettingsPanel error、SessionsSidebar error、MessageList error event、ToolGroupCard pass/fail、ToolRow error。

### 5. 輸入框 placeholder & text 顏色明確化

`Login.tsx` 與 `CustomInstructionsPanel.tsx` 的 input/textarea 補上 `text-claude-text placeholder:text-claude-textFaint`,確保 dark 模式下打字看得見。

---

## 動到的檔案

```
orion-agent/frontend/src/
├── index.css                              # dark CSS variables 重校
├── components/
│   ├── InputBox.tsx                       # bg-white → dark variant + shadow→ring + error red
│   ├── Login.tsx                          # 卡片 / tab / inputs / error 全 dark variant
│   ├── ModelPicker.tsx                    # 按鈕 + dropdown
│   ├── WorkspaceFiles.tsx                 # dropdown
│   ├── CustomInstructionsPanel.tsx        # textareas + error + saved emerald
│   ├── SettingsPanel.tsx                  # stored values 列表 + error
│   ├── PermissionDialog.tsx               # code chip / tool input / 4 個按鈕
│   ├── MessageList.tsx                    # error event + scroll-to-bottom 按鈕
│   ├── SessionsSidebar.tsx                # error 紅字
│   ├── ToolGroupCard.tsx                  # pass/fail 顏色
│   └── ToolRow.tsx                        # error 顏色
```

未動 `lib/theme.ts` / `hooks/useTheme.ts` / `tailwind.config.js`,theme 切換邏輯本來就 work。

---

## 驗證

### Build

```bash
cd orion-agent/frontend
npm run build
```

預期 output:

```
dist/index.html                   ~0.43 kB
dist/assets/index-*.css          ~26 kB    # 含 .dark + dark:* utilities
dist/assets/index-*.js          ~357 kB
✓ built in ~1s
```

確認 dist CSS 含新 dark var:

```bash
grep -o "\.dark{[^}]*}" dist/assets/index-*.css
# 應看到: --c-cream: 26 26 24; ... --c-text: 250 249 245
```

確認 dist CSS 含 dark variant utility:

```bash
grep -c "dark\\\\:bg-claude-panel" dist/assets/index-*.css
# > 0
```

### 手動測試

1. `npm run dev` 啟動
2. 登入後右上 / 左下齒輪 → Settings → Appearance → 選 **Dark**
3. 預期:
   - 主背景變深黑(`#1A1A18`,接近 Claude.ai)
   - Sidebar 比主背景稍亮一階(`#262624`)
   - 輸入框是 panel 色 + 1px 細邊
   - 文字是純奶油白,清楚可讀
   - error 訊息(故意輸錯密碼)是暗紅底 + 淺紅字
   - ModelPicker dropdown 是深色 panel + 深 drop shadow
4. 切回 **Light** → 完全恢復原 Claude.ai light 風格(白卡片 + cream 主背景)
5. 切到 **Follow system** → 跟 OS 切,改 OS 主題 dropdown 即時跟換

---

## 設計取捨

### 為什麼不改 `--c-cream` 在 light 維持白色,而是用 dark variant?

替代方案是新增一層 token(例如 `--c-card`)讓 light=純白、dark=panel。但這會引入第三組顏色語意,對小專案是 over-engineering。Tailwind 本身的 `dark:` variant 就是為這場景設計的 — 只在 dark mode 套用,語意清楚。

### 為什麼 dark text 用純奶油白(`#FAF9F5`)而非保留原 `#EBE9E2`?

對比 Claude.ai 截圖,主文字是 `#FAF9F5`(跟 light cream 同值)。原本的 `#EBE9E2` 看起來灰灰的,沒有「奶油」感。`#FAF9F5` 在 `#1A1A18` 上對比約 16:1,符合 WCAG AAA。

### 為什麼 dark `--c-border` 從 `#383834` 提到 `#40403C`?

dark 模式的卡片(輸入框、dropdown)用 `bg-claude-panel = #262624`,對主背景 `#1A1A18` 只差約 `#0C` 的亮度。如果 border 也接近 panel 色,卡片邊界會完全融入。提到 `#40403C` 後 ring 與 panel 之間有約 `#1A` 的差,卡片邊有清楚的線條,但又不至於 harsh。

### shadow vs ring 的取捨

light mode 的 `box-shadow: 0 1px 3px rgba(0,0,0,0.04)` 是「物體有重量」的感覺;dark mode 沒有自然光源這個 mental model,改用 `ring-1` 更貼近原生 dark UI 慣例。Floating dropdown 仍保留深 shadow 因為「飄起來」這件事在 dark 也成立(陰影更深 `rgba(0,0,0,0.6)`)。

---

## 已知 caveat

### 1. red / emerald 用 Tailwind 預設色階,沒走 token

error / success 訊息我用 `dark:text-red-300` 而非新增一個 `--c-error-text` token。理由:這些是 status 色,不是品牌色,不需要主題化得這麼徹底。如果未來要支援高對比模式或其他主題,再升級成 token 即可。

### 2. PermissionDialog 的 `bg-claude-orangeSoft/40` 在 dark mode

PermissionDialog 整體背景用 `bg-claude-orangeSoft/40`(40% alpha)。dark 的 orangeSoft 是 `#382822`,40% alpha 與底層 cream(`#1A1A18`)混合後仍是深棕暖色,對比 OK,沒有特別處理。已肉眼確認 dark 下 dialog 仍辨識得出橘色 hint。

### 3. MessageBubble 沒動

`MessageBubble.tsx` 完全用 `text-claude-text` / `bg-claude-orangeSoft` / `bg-claude-panel` 等 token,本來就 theme-aware,不需修改。

### 4. WebSocket / API endpoint 不影響

純前端 CSS / className 變更,不動任何 API 或 backend。
