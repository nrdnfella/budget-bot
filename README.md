# Budget bot

A Telegram bot that writes your spending to the Budget Google Sheet and replies with today's limit. Each reply ends with a funny tip, written by a local Ollama model in the style of the Advice tab. If the model is unavailable, the bot uses a line from the tab instead.

All the calculations are formulas in the sheet (Today tab). The bot only adds rows and reads the results.

## Sheet tabs

| Tab | Purpose |
|---|---|
| Today | Daily limit, spent and left today, month and savings totals. The bot reads B3:B19 |
| Forecast | Spending by category (last 90 days), a "what if I cut" calculator and a target-amount planner. Yellow cells are inputs |
| Settings | Income, fixed costs, savings rate, savings goal (B22), morning message hour (B23) |
| Expenses | One row per purchase: date, amount, note, category. The bot appends to it |
| Categories | Keyword → category rules. "кофе" in a note means Coffee. `/cat` adds rows |
| Savings | Deposits (+) and withdrawals (−). Row 2 is the opening balance |
| Advice | Tips by situation. The model uses these as examples; `/teach` adds new rows |
| Лист1 | Your original sheet, unchanged |

How the daily limit works: (free money this month − spent before today) ÷ days left, including today. Anything you don't spend raises tomorrow's limit, and overspending lowers it.

## Setup

### 1. VPS
- Ubuntu 24.04, 2 vCPU, 8 GB RAM, 30 GB disk. The `qwen2.5:3b` model needs about 3 GB of RAM and runs on the CPU.
- Install Docker: `curl -fsSL https://get.docker.com | sh`
- Make sure the VPS can reach Docker Hub and ollama.com, which some regions block. If the model download fails, use a VPS in another region.

### 2. Telegram bot
1. In Telegram, open @BotFather and send `/newbot`.
2. Copy the token.

### 3. Google access (service account)
1. In console.cloud.google.com, create a project and enable the **Google Sheets API**.
2. Go to IAM & Admin → Service Accounts → Create. Then open Keys → Add key → JSON and download the file.
3. Open the Budget sheet, click Share, and add the service account's email (`...@...iam.gserviceaccount.com`) as an **Editor**.

### 4. Run it
```bash
scp -r budget-bot user@your-vps:~/
ssh user@your-vps
cd budget-bot
mkdir -p secrets data
mv ~/your-key.json secrets/service-account.json   # upload the key first
cp .env.example .env && nano .env                 # paste TELEGRAM_TOKEN
docker compose up -d --build
docker compose logs -f bot
```
`ollama-pull` downloads the model once, which takes a few minutes. Until it finishes, tips come from the Advice tab.

### 5. First message
Send `/start` to your bot **before anyone else does**. The first chat to write becomes the owner, and every other chat is ignored. To set the owner explicitly instead, put your chat ID in `OWNER_CHAT_ID`.

Because November started before the bot, send `/earlier <amount>` with what you've spent so far this month. Otherwise today's limit counts the whole month's money as unspent.

## Commands
```
350 coffee            log spending
/today  /month  /savings
/save 10000 [note]    /take 5000 [note]
/earlier 40000        spending this month before the bot
/undo                 remove the last expense
/forecast             spending by category, per month and per year
/whatif coffee        yearly saving from giving up coffee
/whatif taxi 50%      the same for cutting taxi by half
/plan 300000 12       what to cut to save 300 000 in 12 months
/cat starbucks Coffee teach a keyword → category
/teach overspent Your card filed a complaint.
/tip [situation]
```
Situations: overspent, on_track, saving, withdraw, payday, morning, forecast.

## How the forecasts work
- **Categories.** When you log `350 кофе`, the bot looks up the note in the Categories tab. A keyword matches the start of a word, so "кофе" also matches "кофейня". If nothing matches, the first word of the note becomes the category. Add rules with `/cat`, or fix a category directly in the Expenses tab.
- **Monthly average.** Spending over the last 90 days, divided by the months of data you actually have. With only two weeks logged, the bot scales those two weeks up to a month and warns you that the forecast is rough. `/earlier` lump sums are left out.
- **/whatif.** Monthly average × 12 × the share you cut. The query can be a category name ("Coffee"), a keyword from the Categories tab ("кофе"), or any word from your notes ("latte").
- **/plan.** Works out the monthly amount needed to reach the target, subtracts what you already save each month (Settings B19), and covers the rest by cutting the biggest categories by up to 50% each. Rent, family and other fixed costs are never suggested. If halving everything still isn't enough, it gives a realistic timeline instead.

## Teaching the tips
- Add rows to the Advice tab, or use `/teach`.
- The model gets up to 12 tips for the current situation as examples, so more good lines make better jokes.
- To try a different model, change `OLLAMA_MODEL` in `.env` and run `docker compose up -d ollama-pull bot`.

## Teaching the model: levels and materials

There are three ways to teach the model, from cheapest to most work. Move to the next level only when the current one stops giving good results.

| Level | What changes | Cost | When to move on |
|---|---|---|---|
| 1. Examples in the prompt (few-shot) | Nothing in the model; the bot sends Advice tab lines with every request | Free, works now | Jokes repeat the examples too closely, or the tone drifts |
| 2. Custom model via Modelfile | A system prompt and example dialogues are built into the model | Minutes, no GPU | You have 200+ good tips and want the style to stick without sending examples |
| 3. Fine-tuning (LoRA) | The model's weights are trained on your tips | A few hours on a free Colab GPU | Only if level 2 is not enough |

### Level 1: prompting
The bot already does this in `bot/advice.py` (`build_prompt`). To improve results, write more varied tips for each situation and edit the prompt wording.
- [Prompt engineering overview](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview): clear instructions, examples, output format. Written for Claude, but the techniques apply to small models too.
- *Hands-On Large Language Models*, Jay Alammar and Maarten Grootendorst (O'Reilly, 2024), chapter 6 "Prompt Engineering". [O'Reilly page](https://www.oreilly.com/library/view/hands-on-large-language/9781098150952/)

### Level 2: Ollama Modelfile
A Modelfile builds a new local model on top of `qwen2.5:3b`: `SYSTEM` sets the persona, and `MESSAGE user` / `MESSAGE assistant` pairs add example exchanges. Build it with `ollama create budget-jester -f Modelfile`, then set `OLLAMA_MODEL=budget-jester`.
- [Modelfile reference](https://docs.ollama.com/modelfile): `FROM`, `SYSTEM`, `MESSAGE`, `PARAMETER`, `ADAPTER`.

### Level 3: fine-tuning with LoRA
LoRA trains a small adapter on top of the base model, which is cheap enough for a free Colab GPU. The workflow:
1. Export the Advice tab to JSONL (situation → tip pairs).
2. Train with Unsloth in Colab.
3. Export to GGUF, which also generates a Modelfile.
4. Load the result into Ollama on the VPS.

Use the same chat template for training and for running in Ollama. A mismatch is the most common reason a fine-tuned model works in Colab but gives poor output in Ollama.
- [Unsloth: fine-tune Llama 3 and use it in Ollama](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide/tutorial-how-to-finetune-llama-3-and-use-in-ollama): beginner tutorial with free Colab notebooks.
- [Unsloth: saving to Ollama](https://unsloth.ai/docs/basics/inference-and-deployment/saving-to-ollama): GGUF export, quantization choice (`q4_k_m`), troubleshooting.
- [Hugging Face LLM Course](https://huggingface.co/learn/llm-course/chapter1/1): free; chapter 3 covers fine-tuning a pretrained model, and chapter 11 covers chat templates, LoRA and evaluation.

### How LLMs work (background)
- *Build a Large Language Model (From Scratch)*, Sebastian Raschka (Manning, 2024): builds a GPT-style model in PyTorch, then fine-tunes it for classification and for following instructions. Appendix E covers LoRA. [Manning page](https://www.manning.com/books/build-a-large-language-model-from-scratch)
- [Neural Networks: Zero to Hero](https://karpathy.ai/zero-to-hero.html), Andrej Karpathy: free video course that builds neural networks in code, from backpropagation up to GPT.

Suggested order: Level 1 links, then the Modelfile reference, then the Unsloth tutorial. Read Raschka or Karpathy alongside if you want to understand what the training does.

## Updating the code
```bash
docker compose up -d --build bot
```
Tests: `pip install -r requirements.txt pytest && pytest -q tests`
