from pathlib import Path
import json

from symkern.cli import submit_prompt
from symkern.intent_compiler import IntentCompiler


PROMPT = "make up 3 historical dates, lookup on wikipedia.org what deaths occurred on those dates and elect the most illustrious one"


def test_compiler_recognizes_historical_wikipedia_death_prompt() -> None:
    result = IntentCompiler().compile(PROMPT)

    assert result.intent.goals == ["elect_illustrious_historical_death"]
    assert result.intent.state["date_count"] == 3
    assert result.intent.state["lookup_source"] == "wikipedia.org"


def test_historical_prompt_uses_compiled_selector_with_mock_lookup(tmp_path: Path) -> None:
    historical_dates = [
        {"year": 1968, "month": 4, "day": 4, "label": "1968-04-04"},
        {"year": 1821, "month": 5, "day": 5, "label": "1821-05-05"},
        {"year": 1989, "month": 11, "day": 9, "label": "1989-11-09"},
    ]
    lookup = {
        "1968-04-04": [
            {
                "person": "Martin Luther King Jr.",
                "year": 1968,
                "description": "American minister and civil rights leader",
                "wikipedia_url": "https://en.wikipedia.org/wiki/Martin_Luther_King_Jr.",
                "page_count": 1,
            }
        ],
        "1821-05-05": [
            {
                "person": "Napoleon",
                "year": 1821,
                "description": "French emperor and military leader",
                "wikipedia_url": "https://en.wikipedia.org/wiki/Napoleon",
                "page_count": 1,
            }
        ],
        "1989-11-09": [
            {
                "person": "Charles John Pedersen",
                "year": 1989,
                "description": "American chemist and Nobel laureate",
                "wikipedia_url": "https://en.wikipedia.org/wiki/Charles_J._Pedersen",
                "page_count": 1,
            }
        ],
    }

    result = submit_prompt(
        PROMPT,
        artifact_root=tmp_path,
        context={"historical_dates": historical_dates, "historical_death_lookup": lookup},
    )
    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))

    assert result["status"] == "success"
    assert result["backend"]["selection"]["target"] == "c.wikipedia_death_selector"
    assert artifact["outputs"]["selected_death"]["person"] == "Napoleon"
    assert len(artifact["outputs"]["death_candidates"]) == 3
    assert Path(artifact["backend"]["artifacts"]["backend_source"]).exists()
    assert Path(artifact["backend"]["artifacts"]["backend_binary"]).exists()