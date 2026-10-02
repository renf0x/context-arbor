# Operations

- Validate memory: `python arbor.py memory check`
- Search memory: `python arbor.py memory query "question"`
- Archive completed entries: `python arbor.py memory rotate`
- Open Obsidian: `python arbor.py memory open`
- Run tests: `python -m unittest discover -s tests -q`
- Project map / find code / one symbol: `python arbor.py code map`, `code find "topic"`, `code show FILE:SYMBOL`
- Token usage from local transcripts: `python arbor.py stats` (add `--prices ... --save` for cost)
- Chronicle page: `python arbor.py ui --title "Name" --open` (writes `.arbor/ui/index.html`)
- Long sessions: run `/autocompact 200k` once in Claude Code; tune the window with `python arbor.py stats --simulate-compact` (DEC-20261002-001)
