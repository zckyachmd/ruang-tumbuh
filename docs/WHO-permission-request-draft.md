# WHO permission and licence clarification draft

Use this text in the [WHO permissions request form](https://www.who.int/about/policies/publishing/permissions). The form asks for direct links to the material; the links below match the SHA-256 manifest in [WHO-growth-validation.md](WHO-growth-validation.md). Complete WHO's requester and contact fields yourself. Do not submit API keys, family data, or other private project credentials.

## Request text

**Subject:** Licence and permitted use of WHO Child Growth Standards expanded z-score tables in a noncommercial family record application

Dear WHO Permissions Team,

I am developing Ruang Tumbuh, a noncommercial application for families to record child-care events and growth measurements. The application is intended to help parents and caregivers keep a family record. It will be hosted by a noncommercial operator; access is limited to registered families and relatives invited by a family administrator. WHO reference files will remain server-side and will not be offered as direct downloads; authorized users will only see calculated results in the application. It is not offered as a commercial product, is not a diagnostic service, and will not imply WHO endorsement.

Before implementing any WHO comparison, I request written clarification for the ten WHO expanded z-score workbooks listed below:

1. Are these specific workbooks governed by WHO's data compilation terms, another licence, or separate copyright permissions?
2. Does this noncommercial family-record use fall within the terms' “public health purposes” scope?
3. May the application include the unmodified reference values in its deployed instance, transform the workbooks into an internal machine-readable format, and use those values to calculate and display age- and sex-specific comparisons? If any of these steps require prior written authorization, please specify the permission needed.
4. What attribution and disclaimer wording is required? Are any of the files or values credited to third parties?
5. Do the terms permit this hosted deployment with access limited to registered families and invited relatives, where the source workbooks are not directly downloadable and only calculated results are shown? Separately, would making the application source code public without including the WHO source workbooks change the applicable permissions or obligations?

No WHO data, charts, or calculations are currently shipped or displayed by the application. I will keep the feature disabled until the applicable rights and technical validation requirements are resolved. I will not use the WHO name or emblem in a way that implies endorsement.

Thank you for clarifying the applicable terms and any required permission.

## Direct asset links

All files were downloaded for checksum inspection on 2026-11-02; the checksums and byte sizes are recorded in the linked manifest.

- Weight-for-age, girls: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/weight-for-age/expanded-tables/wfa-girls-zscore-expanded-tables.xlsx?sfvrsn=f01bc813_10>
- Weight-for-age, boys: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/weight-for-age/expanded-tables/wfa-boys-zscore-expanded-tables.xlsx?sfvrsn=65cce121_10>
- Length/height-for-age, girls: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/length-height-for-age/expandable-tables/lhfa-girls-zscore-expanded-tables.xlsx?sfvrsn=27f1e2cb_10>
- Length/height-for-age, boys: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/length-height-for-age/expandable-tables/lhfa-boys-zscore-expanded-tables.xlsx?sfvrsn=7b4a3428_12>
- Head circumference-for-age, girls: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/head-circumference-for-age/expanded-tables/hcfa-girls-zscore-expanded-tables.xlsx?sfvrsn=3a34b8b0_8>
- Head circumference-for-age, boys: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/head-circumference-for-age/expanded-tables/hcfa-boys-zscore-expanded-tables.xlsx?sfvrsn=2ab1bec8_8>
- Weight-for-length, girls: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/weight-for-length-height/expanded-tables/wfl-girls-zscore-expanded-table.xlsx?sfvrsn=db7b5d6b_8>
- Weight-for-length, boys: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/weight-for-length-height/expanded-tables/wfl-boys-zscore-expanded-table.xlsx?sfvrsn=d307434f_8>
- Weight-for-height, girls: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/weight-for-length-height/expanded-tables/wfh-girls-zscore-expanded-tables.xlsx?sfvrsn=daac732c_8>
- Weight-for-height, boys: <https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/weight-for-length-height/expanded-tables/wfh-boys-zscore-expanded-tables.xlsx?sfvrsn=ac60cb13_8>

## Before submission

- Confirm the described server-side-only handling of WHO source files matches the intended product before submission.
- Complete WHO's required requester and contact fields yourself.
- Attach or retain the WHO response and reference ID with the asset manifest. Do not enable or distribute WHO comparisons until rights and validation gates pass.
