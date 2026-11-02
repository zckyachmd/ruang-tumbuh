# WHO licence status — request 202611419

The private seven-page permission response supplied by the project owner was read on 2 November 2026. It grants a non-exclusive licence for the requested use of the ten sex-specific expanded z-score workbooks listed in [the asset manifest](who-assets.json). A new permission request is not required for that licensed use.

The approved request describes Ruang Tumbuh as a **noncommercial hosted family record service**, accessible to registered families and relatives invited by a family administrator. Workbooks remain server-side and are not direct downloads; only calculated results are displayed after technical validation. Public source distribution excludes the workbooks. This is not a transferable general licence for source-code users to redistribute WHO materials.

Implementation requirements from the supplied agreement:

- Keep workbooks and derived reference datasets out of the public repository, public container images, static assets, exports and unauthenticated endpoints. Mount them read-only from a protected server directory. Do not distribute the materials separately.
- Retain publication metadata and bibliographical acknowledgements. Do not brand or substantively alter the licensed material, claim WHO affiliation/endorsement, or separately use the WHO logo. Use is subject to the noncommercial context stated in the request; a commercial/advertising use is outside this implementation's scope.
- AI use required for the licensed purpose is allowed, but the materials or data relating to their AI use must not be released into public LLMs or made available for unrestricted third-party reuse without express written authorization. The current external classifier receives **no WHO tables, retrieved excerpts, or calculated WHO results**. Growth calculations and education about the reference run locally.
- Verbatim retrieved excerpts require clear WHO attribution and a source reference. Newly generated text must not be represented as WHO-authored. The implementation uses local application explanations, identifies WHO as the reference source, and does not generate clinical interpretation.
- WHO does not validate this application's calculations or AI output. User notices explain that AI assists documentation; diagnosis and treatment remain the responsibility of health professionals.
- Published validated updates may be used under the agreement; future editions require a new licence. Re-check scope before adding materials outside the ten requested assets, other age references, translations, or another distribution model.
- Original third-party material is outside this grant. Attribution and provenance must identify any separate rights.

The original correspondence contains personal information and is intentionally not committed. The request ID and the scope summary are sufficient for project status; retain the original privately with operational records.

## Bibliographical acknowledgements

Reproduced or calculated from:

- WHO Multicentre Growth Reference Study Group. *WHO child growth standards: length/height-for-age, weight-for-age, weight-for-length, weight-for-height and body mass index-for-age: methods and development.* Geneva: World Health Organization; 2006. © World Health Organization 2006.
- WHO Multicentre Growth Reference Study Group. *WHO child growth standards: head circumference-for-age, arm circumference-for-age, triceps skinfold-for-age and subscapular skinfold-for-age: methods and development.* Geneva: World Health Organization; 2007. © World Health Organization 2007.

Source: https://www.who.int/tools/child-growth-standards

The agreement also names the 2009 growth-velocity work and the 2007 school-age reference. Neither is implemented or bundled by this change; their mention does not enlarge the ten-asset scope of the submitted request.

## Installation and validation

`python scripts/install-who-data.py /protected/who-data` downloads only the ten manifest assets and verifies SHA-256. Do not use the public web directory or commit the resulting files. Set `WHO_DATA_DIR` to that directory. Mount it read-only into the API; the chat worker has no dataset mount.

`WHO_COMPARISON_ENABLED` defaults to `0`. Before enabling, install a private `validation.json` record containing `status: approved`, named `reviewer`, an `independent_fixture_report` reference, and the reviewed `asset_sha256` list. This record attests an actual review; synthetic LMS tests are **not** that review. Validate both sexes, every enabled indicator, age boundaries, missing inputs, unit/position handling and comparison displays against independently sourced official reference outputs. Position conversions and off-grid length interpolation are currently withheld, not guessed.

The restricted local runner could not download assets; the dedicated GitHub CI job did download all ten checksum-pinned workbooks privately, pass 94,864 numerical and loader/boundary checks, then remove the assets. No clinical review or production activation review is claimed. Keep production comparison disabled until the validation record is reviewed. Raw measurement trends can still be displayed.
