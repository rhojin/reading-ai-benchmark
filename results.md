# Reading AI Benchmark

Speed and cost of AI-generated reading-comprehension questions per book chapter, for big and small models.

- **Book:** Alice's Adventures in Wonderland by Lewis Carroll (Project Gutenberg #11, book_id `4e04ea77acf3b021`), 12 of 12 chapters
- **Questions:** 6 per chapter (2 easy, 2 medium, 2 hard), each with a short expected answer
- **Run:** 2026-10-28 19:13 UTC, spent $0.7000 of the $0.9949 budget
- **Costs** are the real costs OpenRouter reported for each request (usage accounting), not estimates.
- **Scope:** one book and one run per mode, so timings vary. Read times are measured on the server, without the network a real app adds. The quality check covers the two sample chapters only.

> **Note:** GPT-6 Luna: chapter 1 (both modes) and chapter 2 (parallel) were served from OpenAI's automatic prompt cache, because the 2-chapter test run had sent the same prompts minutes earlier. Those 3 replies cost about two thirds less. For a new book, Luna would cost about $0.0075 per book (sequential) and $0.0065 (parallel), and its summary overhead would be about +17% instead of +25%.

> **Note:** OpenAI models (all replies served by Azure) were billed about 18% above tokens x the list price shown in the table; the Anthropic models exactly at list price. All costs in this report are the billed amounts.

## 1. Model comparison

|  | Big: `anthropic/claude-sonnet-5.5` | Small: `anthropic/claude-haiku-5.5` | Big: `openai/gpt-6.1-sol` | Small: `openai/gpt-6-luna` |
| --- | ---: | ---: | ---: | ---: |
| List price per 1M tokens (input / output) | $2.00 / $10.00 | $0.10 / $0.50 | $2.00 / $10.00 | $0.10 / $0.50 |
| Reasoning effort | low | none | low | none |
| **Time per book**: sequential, with summary | 66.9 s | 58.3 s | 140.0 s | 37.4 s |
| **Time per book**: 4 parallel, no summary | 14.4 s | 11.0 s | 30.0 s | 9.6 s |
| **Time to first chapter**: sequential, with summary | 5.3 s | 7.4 s | 10.1 s | 3.2 s |
| **Time to first chapter**: 4 parallel, no summary | 4.5 s | 3.1 s | 8.4 s | 3.2 s |
| Average time per chapter (one request) | 5.6 s | 4.9 s | 11.7 s | 3.1 s |
| **Cost per book**: with summary | $0.2104 | $0.0128 | $0.1544 | $0.00715 |
| **Cost per chapter**: with summary | $0.0175 | $0.00106 | $0.0129 | $0.00060 |
| Cost per book: no summary | $0.1724 | $0.00914 | $0.1280 | $0.00573 |
| Tokens per book with summary: prompt / completion (reasoning) | 68,056 / 7,427 (0) | 77,925 / 9,968 (0) | 46,132 / 3,907 (0) | 45,130 / 3,762 (0) |
| **Invalid JSON replies** (both modes) | 0 of 24 | 2 of 26 | 0 of 24 | 0 of 24 |
| Retries after rate limits / server errors | 0 | 0 | 0 | 0 |
| **Extra cost of the running summary** | +$0.0380 per book (+22%) | +$0.00238 per book (+26%, from 10 of 12 chapters) | +$0.0263 per book (+21%) | +$0.00142 per book (+25%) |
| Extra tokens per book from the summary: prompt / completion | +10,335 / +1,733 | +13,110 / +2,143 | +6,159 / +1,095 | +5,157 / +858 |

- *Time to first chapter*: until chapter 1's questions were validated and stored, i.e. when a family can start reading.
- *Extra cost of the running summary*: run with summary (in and out) minus run without, compared chapter by chapter. The prompt-token difference is exact; completion tokens also vary a little from run to run.
- *Reasoning*: `claude-sonnet-5.5` (effort `low`) and `gpt-6.1-sol` (effort `low`) reported 0 reasoning tokens, i.e. they answered without a separate thinking step.

## 2. Time until the first questions

A family can start reading as soon as chapter 1's questions exist. Chapter 2's are only needed once the child has finished chapter 1, so the rest of the book can be generated in the background. The table separates the two steps: showing chapter 1 first, and letting a faster small model write it (times from the sequential runs).

|  | Anthropic | OpenAI |
| --- | ---: | ---: |
| App waits for the whole book (big model, sequential) | 66.9 s | 140.0 s |
| App shows chapter 1 first (big model) | 5.3 s (`claude-sonnet-5.5`) | 10.1 s (`gpt-6.1-sol`) |
| Chapter 1 written by the small model instead | 7.4 s (`claude-haiku-5.5`, incl. 1 JSON retry) | 3.2 s (`gpt-6-luna`) |

- **Anthropic:** showing chapter 1 first cut the wait from 66.9 s to 5.3 s; the small model was 2.1 s slower for chapter 1 (parallel run: 3.1 s vs. 4.5 s).
- **OpenAI:** showing chapter 1 first cut the wait from 140.0 s to 10.1 s; the small model then cut it to 3.2 s (parallel run: 3.2 s vs. 8.4 s).

## 3. Second family: load from SQLite vs. generate again

|  | Big: `anthropic/claude-sonnet-5.5` | Small: `anthropic/claude-haiku-5.5` | Big: `openai/gpt-6.1-sol` | Small: `openai/gpt-6-luna` |
| --- | ---: | ---: | ---: | ---: |
| Generate all questions again: sequential, with summary | 66.9 s, $0.2104 | 58.3 s, $0.0128 | 140.0 s, $0.1544 | 37.4 s, $0.00715 |
| Generate all questions again: 4 parallel, no summary | 14.4 s, $0.1724 | 11.0 s, $0.00914 | 30.0 s, $0.1280 | 9.6 s, $0.00573 |
| **Load all stored questions from SQLite** (average of 100 reads) | 0.57 ms for 72 questions, $0 | 0.59 ms for 72 questions, $0 | 0.57 ms for 72 questions, $0 | 0.59 ms for 72 questions, $0 |

The read time is measured inside the server process. A real app adds the network round-trip to the family's device, for stored and freshly generated questions alike.

## 4. Cost for 1,000 families reading this book

|  | Big: `anthropic/claude-sonnet-5.5` | Small: `anthropic/claude-haiku-5.5` | Big: `openai/gpt-6.1-sol` | Small: `openai/gpt-6-luna` |
| --- | ---: | ---: | ---: | ---: |
| **Without shared storage:** 1,000 × generation | $210.38 | $12.78 | $154.38 | $7.15 |
| **With shared storage:** 1 × generation + 999 reads from SQLite | $0.2104 | $0.0128 | $0.1544 | $0.00715 |
| Saving | 99.9% | 99.9% | 99.9% | 99.9% |
| Wait for chapter 1's questions: without → with shared storage | 5.3 s → 0.57 ms + network | 7.4 s → 0.59 ms + network | 10.1 s → 0.57 ms + network | 3.2 s → 0.59 ms + network |

This assumes all 1,000 families read this one book. With many books, the saving depends on how many families share each book, but a book's questions are always paid for only once. Generation cost = the sequential run with summary; reads from SQLite make no AI call, so they cost no AI money.

## 5. Sample chapters side by side

The stored question sets (sequential run, with running summary), grouped by level, so you can judge the quality yourself. Every chapter of every model is in [`questions.json`](questions.json).

### Chapter 1: Down the Rabbit-Hole

| Level | Big: `anthropic/claude-sonnet-5.5` | Small: `anthropic/claude-haiku-5.5` | Big: `openai/gpt-6.1-sol` | Small: `openai/gpt-6-luna` |
| --- | --- | --- | --- | --- |
| easy | **Q:** What kind of animal did Alice see running by with a watch in its waistcoat pocket?<br>**A:** A White Rabbit with pink eyes. | **Q:** What does Alice see the White Rabbit take out of its waistcoat-pocket?<br>**A:** A watch, which it looks at before hurrying on. | **Q:** What did the White Rabbit take out of its waistcoat pocket?<br>**A:** The White Rabbit took out a watch. | **Q:** What did the White Rabbit take out of its waistcoat pocket?<br>**A:** It took out a watch and looked at it. |
| easy | **Q:** What was the name of Alice's cat?<br>**A:** Dinah. | **Q:** What is written on the paper label of the little bottle Alice finds on the glass table?<br>**A:** The words "DRINK ME," printed in large letters. | **Q:** What did Alice find behind the low curtain in the hall?<br>**A:** Alice found a little door behind the curtain. | **Q:** What words were written on the little bottle?<br>**A:** The bottle was labeled “DRINK ME.” |
| medium | **Q:** Why did Alice run across the field and jump down the rabbit-hole?<br>**A:** She was very curious because she had never seen a rabbit with a waistcoat-pocket and a watch. | **Q:** Why does Alice decide to check the bottle before drinking from it?<br>**A:** She remembers stories of children who got hurt by not following safety rules, so she checks whether it is marked poison first. | **Q:** Why did Alice follow the White Rabbit?<br>**A:** Alice was curious because she had never seen a rabbit with a waistcoat pocket and a watch before. | **Q:** Why did Alice run after the White Rabbit?<br>**A:** She was curious because it had a waistcoat pocket and a watch, and it hurried into a rabbit-hole. |
| medium | **Q:** Why did Alice check the bottle before she drank from it?<br>**A:** She wanted to see if it was marked 'poison', because she had read that unsafe things can hurt you. | **Q:** Why can't Alice get the little golden key from the glass table after she shrinks?<br>**A:** She is too small to reach the table, and the table legs are too slippery for her to climb up. | **Q:** Why couldn't Alice reach the golden key after drinking from the bottle?<br>**A:** She had shrunk so small that she could not reach the key on the table. | **Q:** Why couldn’t Alice go through the little door into the garden at first?<br>**A:** She was too big to fit through the small doorway. |
| hard | **Q:** Alice ate the cake even though she did not know what it would do. Do you think that was a good idea? Why or why not?<br>**A:** Any opinion is fine if it gives a reason, like she needed to try something to reach the key, or it could have been risky. | **Q:** Why do you think Alice keeps talking to herself and giving herself advice? Do you ever do something like that?<br>**A:** A good answer says that talking to herself helps her feel less alone and think things through, and connects it to the child's own experience. | **Q:** Do you think Alice made a good choice by following the Rabbit into its hole?<br>**A:** A good answer gives an opinion and uses something from the chapter, such as her curiosity or not knowing how to get out. | **Q:** Do you think Alice was wise to drink from the bottle? Why or why not?<br>**A:** A good answer gives an opinion and a reason, such as noting she checked that the bottle was not marked poison. |
| hard | **Q:** What do you think Alice will do next to get into the garden, and what might happen to her?<br>**A:** A good answer guesses a sensible next step, like trying the cake again, finding the key, or changing size, and gives a reason. | **Q:** Alice says she is starting to think very few things are really impossible. Do you think she is right, and what might happen next to prove it?<br>**A:** A good answer gives the child's opinion with a reason, such as the strange events so far, and predicts a surprising thing that could happen next in the garden or hall. | **Q:** What do you think will happen to Alice after she finishes the cake?<br>**A:** A good answer predicts what will happen and links it to the bottle changing her size or her hopes about the cake. | **Q:** What do you think Alice will try next to get into the garden?<br>**A:** A good answer makes a prediction based on what Alice has tried, such as using the cake to change her size. |
| *summary* | Alice, feeling bored by the riverbank, follows a White Rabbit with a watch down a rabbit-hole and falls into a strange hall with locked doors. She finds a tiny door to a lovely garden and drinks a 'DRINK ME' bottle, which makes her small, but then she cannot reach the golden key and eats a cake marked 'EAT ME'. | Alice, bored by the riverbank, follows a talking White Rabbit with a pocket watch down a deep rabbit-hole and falls a long way into an underground hall. She finds a tiny golden key and a small door to a beautiful garden, then drinks from a bottle and eats a cake that make her shrink and grow. The chapter ends with Alice small and crying, unable to reach the key she needs to get into the garden. | Alice follows a White Rabbit with a watch down a rabbit-hole and lands in a hall with locked doors. She finds a tiny door leading to a lovely garden, but a drink makes her too small to reach the key she left on the table. She eats a cake marked “EAT ME,” hoping it will help her get into the garden. | Alice follows a hurried White Rabbit down a rabbit-hole and lands in a hall full of locked doors. She finds a key to a tiny door into a lovely garden, drinks from a bottle and shrinks, but cannot reach the key; she then eats a cake, hoping it will change her size. |

### Chapter 12: Alice’s Evidence

| Level | Big: `anthropic/claude-sonnet-5.5` | Small: `anthropic/claude-haiku-5.5` | Big: `openai/gpt-6.1-sol` | Small: `openai/gpt-6-luna` |
| --- | --- | --- | --- | --- |
| easy | **Q:** What happened to the jury-box when Alice jumped up?<br>**A:** Alice tipped it over with her skirt, and all the jurymen fell out onto the heads of the crowd. | **Q:** Who does the King ask to be the next witness, and who calls her out?<br>**A:** Alice is called as the next witness, and the White Rabbit calls her out after the Knave's verses are found. | **Q:** What did Alice knock over when she jumped up?<br>**A:** Alice knocked over the jury-box with the edge of her skirt. | **Q:** What did Alice knock over when she jumped up?<br>**A:** She knocked over the jury-box. |
| easy | **Q:** Where did Alice find herself at the end, and who was with her?<br>**A:** She was lying on the riverbank with her head in her sister's lap. | **Q:** What does the White Rabbit say he found and read to the court?<br>**A:** He found a paper with a set of verses, which he read aloud to the court as possible evidence. | **Q:** Who was beside Alice when she woke up?<br>**A:** Alice’s sister was beside her, with Alice’s head resting in her lap. | **Q:** Where did Alice find herself when the cards flew at her?<br>**A:** She found herself lying on the bank with her sister. |
| medium | **Q:** Why did the Queen and King say Alice had to leave the court?<br>**A:** The King read a rule saying anyone over a mile high must leave, and they said Alice was that tall. | **Q:** Why does the King say the verses prove the Knave's guilt, and why does Alice disagree?<br>**A:** The King says the Knave did not sign them, which means he must have meant mischief. Alice disagrees because the verses make no sense and nobody even knows what they are about. | **Q:** Why did Alice hurry to put the jurymen back in the jury-box?<br>**A:** She remembered spilling her goldfish and felt that the jurymen might die if she did not put them back quickly. | **Q:** Why did Alice pick up the jurymen after knocking over their box?<br>**A:** She thought they had to be put back quickly or they might die, like the goldfish she once upset. |
| medium | **Q:** Why did the Queen shout 'Off with her head!' at Alice?<br>**A:** Alice said the idea of 'sentence first, verdict afterwards' was nonsense and refused to hold her tongue, so the Queen got very angry. | **Q:** Why does Alice suddenly wake up on the riverbank, and what has been happening to her?<br>**A:** She wakes because the pack of cards flies at her and she tries to beat them off; she was asleep and had been dreaming all along. | **Q:** Why was Alice no longer afraid to interrupt the King?<br>**A:** Alice had grown so large that she was no longer afraid to interrupt him. | **Q:** Why did Alice say the paper did not prove the Knave was guilty?<br>**A:** She said nobody even knew what the verses were about. |
| hard | **Q:** Alice says 'You're nothing but a pack of cards!' Why do you think she was brave enough to say it now, when she was not so brave before?<br>**A:** Any sensible answer, such as: she had grown to full size and felt big and strong, or she was tired of the unfair trial and the Queen's bullying. | **Q:** What do you think about how Alice stands up to the King and Queen in this chapter, and why do you think she does it?<br>**A:** A good answer gives a personal opinion, such as admiring her bravery or honesty, and explains why, like her being fed up with their unfair rules or silly rulings. | **Q:** In the croquet game, Alice helped others hide from the Queen; now she talks back to her. How has Alice changed?<br>**A:** A good answer describes Alice becoming braver and uses her earlier hiding and her later talking back as examples. | **Q:** Do you think the King’s rule about people over a mile high was fair to Alice? Why?<br>**A:** A good answer gives an opinion and explains it, such as saying it was unfair because the King had just made up the rule. |
| hard | **Q:** Early in the story Alice fell down a rabbit-hole into a strange world. How does the ending, waking up by the riverbank, connect to the beginning? What do you think about that ending?<br>**A:** A good answer notes that Alice began bored by the riverbank and ends there, so it was all a dream, and gives an opinion about the ending. | **Q:** Earlier in the story Alice meets the Mouse and the Mock Turtle. How does the ending of this chapter connect with the rest of Alice's adventures, and what might happen if she dreams of Wonderland again?<br>**A:** A good answer connects the dream to earlier events like the trial, the Queen's orders, and creatures she met, and predicts a plausible next adventure or lesson Alice might learn. | **Q:** Do you think Alice would enjoy telling other children about her dream when she grows up?<br>**A:** A good answer gives an opinion and supports it with something from the chapter, such as Alice calling her dream wonderful. | **Q:** Earlier, Alice met a pig that had been a baby. What do these strange changes make you think might happen if Alice dreams of Wonderland again?<br>**A:** A good answer makes a reasonable prediction and connects it to the strange changes in Wonderland, such as guessing Alice or another character might change again. |
| *summary* | Alice, now huge, accidentally upsets the jury and then argues with the King and Queen as they use silly rules and nonsense verses to blame the Knave. When the Queen shouts 'Off with her head!', Alice calls them just a pack of cards, and they fly at her. She wakes up by the riverbank, tells her sister about her dream, and her sister then dreams of Wonderland too. | At the trial, Alice accidentally upsets the jury, then gets called as a witness and grows to a huge size. The King and Queen argue over a mysterious set of verses, and Alice refuses to accept their unfair rules, until the pack of cards attacks her. She wakes on the riverbank beside her sister, who dreams of Wonderland and imagines Alice growing up and telling stories to her own children. | Alice knocks over the jury-box, then challenges the King and Queen’s unfair ideas about the trial. When she calls them a pack of cards, they fly at her, and she wakes beside her sister, realizing Wonderland was a dream. After hearing Alice’s adventures, her sister imagines Wonderland and pictures Alice sharing stories with children when she grows up. | Alice knocks over the jury-box, then tells the court the verses do not prove the Knave is guilty. When the Queen orders her head cut off, Alice calls the court a pack of cards and wakes up beside her sister, realizing Wonderland was a dream. |

## 6. Quality check: usable questions for a child of 8-10

Reviewer: Claude (AI assistant), checked against the book text - a quick plausibility check, not a teacher's assessment. A question counts as usable if a parent could ask it as written: clear for the age, answerable from the story, with a correct expected answer. Two-part questions still count as usable; the 'Asks two things' column shows how many break the prompt's 'one thing per question' rule (a 'Why?' after an opinion question is not counted).

| Model | Chapter 1 | Chapter 12 | Asks two things | Not usable, and why |
| --- | --- | --- | --- | --- |
| Big: `anthropic/claude-sonnet-5.5` | 6/6 | 6/6 | 3/12 | - |
| Small: `anthropic/claude-haiku-5.5` | 6/6 | 4/6 | 7/12 | Ch. 12: Easy 1: the expected answer gets the order wrong (Alice is called at the end of chapter 11, before the verses turn up). Hard 2: muddled - names the Mouse and the Mock Turtle, then asks two other things. |
| Big: `openai/gpt-6.1-sol` | 6/6 | 6/6 | 0/12 | - |
| Small: `openai/gpt-6-luna` | 6/6 | 6/6 | 0/12 | - |

## 7. Age-based mix from the same stored set (no extra AI call)

`pick_questions_for_age()` in `backend/age_mix.py` picks from the stored set of chapter 1 (Down the Rabbit-Hole, `anthropic/claude-sonnet-5.5`). Rules: up to 7: 2 easy, 1 medium; 8-9: 1 easy, 2 medium, 1 hard; 10+: 2 medium, 2 hard.

**Age 7** (3 questions)

1. *easy*: What kind of animal did Alice see running by with a watch in its waistcoat pocket?<br>Expected: A White Rabbit with pink eyes.
2. *easy*: What was the name of Alice's cat?<br>Expected: Dinah.
3. *medium*: Why did Alice run across the field and jump down the rabbit-hole?<br>Expected: She was very curious because she had never seen a rabbit with a waistcoat-pocket and a watch.

**Age 10** (4 questions)

1. *medium*: Why did Alice run across the field and jump down the rabbit-hole?<br>Expected: She was very curious because she had never seen a rabbit with a waistcoat-pocket and a watch.
2. *medium*: Why did Alice check the bottle before she drank from it?<br>Expected: She wanted to see if it was marked 'poison', because she had read that unsafe things can hurt you.
3. *hard*: Alice ate the cake even though she did not know what it would do. Do you think that was a good idea? Why or why not?<br>Expected: Any opinion is fine if it gives a reason, like she needed to try something to reach the key, or it could have been risky.
4. *hard*: What do you think Alice will do next to get into the garden, and what might happen to her?<br>Expected: A good answer guesses a sensible next step, like trying the cake again, finding the key, or changing size, and gives a reason.

## How it was measured

- One OpenRouter request per chapter (`/api/v1/chat/completions` with `"usage": {"include": true}`); every cost is the `usage.cost` that OpenRouter returned.
- **Sequential, with summary:** one chapter after another. Each prompt contains the 2-3 sentence summaries of all earlier chapters, and the reply adds one for the current chapter.
- **4 parallel, no summary:** 4 requests at a time; the chapters don't depend on each other.
- **Run order:** every model's sequential run first (cheap models first), then the parallel runs. A parallel run only starts if it fits in the remaining budget.
- **Reasoning:** every model runs at the lowest reasoning effort it allows. Reasoning tokens are billed as completion tokens and are included in all costs.
- **Invalid JSON:** a reply that isn't valid JSON or doesn't contain exactly 2 easy, 2 medium and 2 hard questions (plus the summary in sequential mode). The chapter is then requested again.
- **Second family:** `load_book_questions()` opens SQLite, reads all stored questions of the book and returns them; the time is the average of 100 reads.
- Timings come from single runs and vary with network and provider load.
- OpenAI caches repeated prompts automatically for a while, and cached input is much cheaper. A run shortly after an earlier one can therefore look cheaper for OpenAI models.
- Prompts: [`prompts/`](prompts/). Raw numbers, including per-chapter rows: [`results.json`](results.json). Every stored question set: [`questions.json`](questions.json). The local `benchmark.db` (not in git) holds everything, including earlier test runs.
