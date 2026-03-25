# Medical Form Extraction

Pay special attention to:
- Patient name may appear as "Last, First" or "First Last" — normalize to "First Last".
- Date of birth may be abbreviated as DOB.
- Insurance ID may be labeled "Member ID", "Policy #", "Subscriber ID", etc.
- Diagnosis codes (ICD-10) look like: A00.0, M54.5, E11.9, etc.
- Procedure codes (CPT) look like: 99213, 99214, 27447, etc.
- Multiple diagnosis or procedure codes may be listed — capture all of them.
- Provider name vs facility name: the provider is the individual doctor, the facility is the hospital/clinic.
