# House style for commentary

MarketPulse commentary uses plain English. It is inspired by ASD-STE100 Simplified Technical English (Issue 9, 2025), in the "STE-flavoured" mode of the `danyuchn/asd-ste100-skill` repo (MIT). We use the principles only. We do not claim STE compliance, and we do not copy the ASD dictionary (it may not be redistributed).

## Rules
1. One idea per sentence.
2. Short sentences: 20 words or fewer.
3. Active voice. Name the actor: "Stocks fell", not "A decline was seen".
4. Simple tenses. Avoid "has been", "would have".
5. A number behind every claim.
6. One meaning per word. Use the glossary. Do not rotate synonyms.
7. No semicolons, no hedge stacks, no marketing adjectives ("massive", "stellar").
8. End with **What to do**: one to three instructions, in the imperative.
9. Explain jargon on first use, or replace it ("10-day average" instead of "10 EMA" in prose).

## Glossary (fixed meanings)
| Word | Meaning |
|---|---|
| Strong / Healthy / Mixed / Weak / Very weak | Mood score bands ≥70 / 55–69 / 45–54 / 30–44 / <30 |
| Cooling fast / Improving fast | % above 10 EMA moved more than 10 points over the lookback |
| Expansion / Contraction | Breadth flag from Pulse §4 |
| Unusual move | Daily change > 2σ of the reading's last 60 daily changes |
| Short-term breadth | % of stocks above the 10-day average |
| Medium trend | % of stocks above the 50-day average |
| Long-term trend | % of stocks above the 200-day average |
| Money moving in / out | Turnover share above / below its 20-day average |

## Example
Bad: "Breadth thrust dynamics have deteriorated materially as participation metrics roll over, suggesting a defensive posture may be warranted."

Good: "Short-term breadth fell. 48% of stocks are above their 10-day average. Five sessions ago, the number was 63%. **What to do:** Do not chase breakouts today. Keep your current positions."

## Tooling
Run `scripts/ste-lint.py` from the skill repo on the commentary templates in CI. It checks semicolons, passive voice, present perfect, long sentences, nominalisations, marketing adjectives and synonym rotation.
