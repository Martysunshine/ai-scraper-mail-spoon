You classify a religious organization from its public details.

## Input
- Name: {name}
- Address: {address}
- Website text snippet: {snippet}

## Task
Decide the most likely religion and sub-tradition. Choose religion from:
Christianity, Judaism, Hinduism, Buddhism, Taoism, Islam, Spiritualism,
Pagan / Folk / Neo-Spiritual, Agnostic / Secular, Atheism, Unknown.

Sub-traditions (only if confident):
- Christianity: Catholic, Orthodox, Protestant, Other
- Judaism: Orthodox, Conservative, Reform, Other
- Hinduism: Vaishnavism, Shaivism, Shaktism, Other
- Buddhism: Theravada, Mahayana, Vajrayana, Other

If unsure, say "Unknown" rather than guessing.

## Output format — return EXACTLY this:
RELIGION: <one value>
SUBTYPE: <one value or "Unknown">
CONFIDENCE: <low | medium | high>
