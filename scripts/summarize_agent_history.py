"""Recompute phase-specific historical counts; never pool task families."""
from collections import defaultdict
import json
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1]/'reports/agent_study_history/episode-summary.json'


def summarize(rows: list[dict]) -> list[dict]:
    seen=set()
    groups=defaultdict(list)
    for row in rows:
        if type(row['full_pass']) is not bool:
            raise ValueError('pass_flag_must_be_boolean')
        key=tuple(row[k] for k in ('study','phase','case','arm','repetition'))
        if key in seen:
            raise ValueError('duplicate_episode_record')
        seen.add(key)
        groups[row['study'],row['phase'],row['arm']].append(row)
    return [{'study':study,'phase':phase,'arm':arm,'episodes':len(batch),
             'distinct_cases':len({r['case'] for r in batch}),
             'historical_full_passes':sum(r['full_pass'] for r in batch)}
            for (study,phase,arm),batch in sorted(groups.items())]


if __name__=='__main__':
    print(json.dumps(summarize(json.loads(SOURCE.read_text())),indent=2))
