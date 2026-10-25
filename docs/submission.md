# Submission checklist

Source: instructor announcement supplied by the team; technical content from assignment §24 pp33–34. Deadline and final team name remain unknown.

## Required direct uploads

| Deliverable | Requirement |
|---|---|
| SME_TEAMNAME_PROJECT_Midterm.pdf | Exact main report pattern; replace TEAMNAME |
| Team video | 20–30 minutes; all members participate; premise, entire source walkthrough, results, embedded demos |
| Single source ZIP | Source, interfaces, launch/config, data, model, training/evaluation, tests, evidence, supporting files |

At most 10 files total; each file at most 1 GB. Use less than 1,000,000,000 bytes as a conservative packaging gate. No external links anywhere in submitted materials. Leader uploads; every other member logs in and verifies every document.

## Report plan

Suggested 12–18 pages excluding appendices: requirements, M1 map, architecture, exact interfaces, state machines, algorithms, data split, safety, T01–T18 measured results, limitations, reproduction and individual contributions.

## Assignment §24.1 p33 package contents (inside the uploads above)

- **Source snapshot:** Python packages, interface definitions, launch files, parameters,
  map, scenario files, tests, dependency versions, license notices (e.g. the NanoDet
  Apache-2.0 file) and the commit hash.
- **Evidence directory:** annotated videos, representative rosbags, full metric CSVs,
  training/evaluation scripts, model artifact, and enough input data to reproduce the
  results (or lawful download instructions; N forbids external links, so include the
  data directly).
- **Individual defense:** each student explains one publisher/subscriber path, one
  service or action lifecycle, and one failed test they corrected.
- **Rubric (A §24.2):** a failed test stays in the report with its diagnosis.

Current gaps against these items are listed in the [compliance register](compliance.md).

## Proposed 25-minute video

| Minutes | Content |
|---|---|
| 0–3 | Premise, map, architecture |
| 3–13 | Full source walkthrough shared among members |
| 13–21 | Integrated S1–S9 demos |
| 21–25 | Results, failures, limitations, contributions |

The 8-minute demonstration structure in A §24.1 p33 and H §7.3 p16 can be embedded. N governs total duration.

## Release gates

- [ ] All mandatory scenarios and exact contracts reviewed.
- [ ] T01–T18 actual evidence included; failures and omissions disclosed.
- [ ] Fresh-checkout reproduction completed.
- [ ] Report claims agree with recorded values.
- [ ] Video duration and every member's participation checked.
- [ ] All required assets included without download dependency.
- [ ] Separate submission copy contains no external links in PDF, text, source comments, manifests, video slides/overlays or archive contents.
- [ ] GitHub development references removed from submission copies without damaging required code.
- [ ] Secrets, caches, build/install/log directories and unnecessary raw footage excluded.
- [ ] Every upload below conservative size gate; checksums and archive extraction verified.
- [ ] Leader uploaded; all other members validated.

Do not ZIP the whole Git checkout blindly: development docs contain external links. Packaging must prepare and audit an allowlisted staging tree. Scan machine-readable text and PDF hyperlinks/text, then manually review video and image content.
