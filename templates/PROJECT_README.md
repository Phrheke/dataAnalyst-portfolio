# [Project title — a question or a claim, not "Analysis of X"]

**Question:** [the business question in the language a stakeholder would use,
not the technical one. Two sentences maximum.]

**Answer in one paragraph.** [Lead with the finding and the recommendation. A
reader who stops here should still have learned the thing. Put the number in
bold. End with **Recommendation:** and a specific action someone could take on
Monday.]

---

## The [N] findings

### 1. [The finding as a sentence, not a topic]
[Two or three sentences. The number, what it means, and why it matters.]

→ `path/to/query.sql`, Q1. [The technique, and why this one rather than the
obvious alternative.]

### 2. [...]

---

## Supporting findings

- **[Finding].** [One or two sentences.] (Q4)

---

## What I would do next

1. **[The most important next step.]** [Why it matters more than the others.]
2. **[...]**

Ordered by value, not by effort. The first item should be the thing you would
actually do on Monday.

---

## Caveats and limitations

**[The assumption that most affects the result.]** [What it is, where it is
declared in code, and how many rows it touches.]

**[Anything that looks wrong but is not.]** [Explain it before a reader has to
ask. If a chart has a counterintuitive shape, say why here.]

**[What this data cannot tell you.]** [The competing explanation you cannot rule
out. Every analysis has one.]

**[Any bug you found in your own work.]** [How you noticed it matters as much as
the fix. "My dashboard disagreed with my README" is a better sentence than "I
fixed a bug".]

---

## Technique index

For anyone scanning for specific skills:

| Technique | Where |
|---|---|
| [e.g. window functions] | Q1, Q4 |

---

## Run it

```bash
make [target]
```

[Every number above must be reproducible by a command here. If it is not,
either add the command or delete the number.]

## Files

```
[tree, with a one-line purpose per file]
```
