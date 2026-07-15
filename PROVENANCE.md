# ACLF data provenance

Verified read-only on Quartz on 2026-07-15.

## Identifier chain

```text
INPCR report_id (note filename)
  -> INPCR global_person_id
  -> time-varying global_patient_id (GPID)
  -> persistent OMOP person_id
```

The pipeline uses the persistent OMOP v1 `person_id` as `sample_id`. GPIDs and
report IDs are retained only as evidence provenance. Patients must never be
deduplicated by GPID.

Observed contracts:

- `mapped_report_ids.csv`: 13,789 rows, 13,789 unique report IDs, 516 GPIDs,
  and 500 OMOP person IDs.
- `patient_roster.csv`: 499 persistent OMOP person IDs.
- Roster overlap with OMOP v1 `person.parquet`: 499/499.
- Roster overlap with OMOP v2 `person.csv`: 0/499. OMOP v2 is not used.
- All 13,789 mapped reports exist: 11,122 in `redacted_txt` and 2,667 in
  `redacted_pdf-text`.
- `note_dates.csv` contains dates for 10,513 reports. Date-filtered retrieval
  excludes undated notes instead of assigning them to an episode.

## Authoritative Quartz inputs

```text
/N/project/depot/hw56/aud/cirrhosis_regv20/data_tables_v1/parquet
/N/project/depot/hw56/aud/cirrhosis_regv20/redacted_txt
/N/project/depot/hw56/aud/cirrhosis_regv20/redacted_pdf-text
/N/project/depot/hw56/aud/medace_aud/resources/mapped_report_ids.csv
/N/project/depot/hw56/aud/medace_aud/resources/patient_roster.csv
/N/project/depot/hw56/aud/medace_aud/resources/note_dates.csv
```

The v1 procedure parquet is misspelled `procedure_ocurrence.parquet`; the EHR
builder detects both spellings.

## Episode selection

OMOP visit concept `9201` is verified as `Inpatient Visit` in this dataset.
Candidate hospitalizations are ranked by a transparent partial structured
proxy using peak total bilirubin, creatinine, and INR linked by
`visit_occurrence_id`. The proxy does not include brain, circulation, or
respiration and is never treated as the final ACLF grade. The agent must verify
all six organs and the episode context from retrieved evidence.
