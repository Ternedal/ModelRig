# DC-L05 mutation results

Status: **source mutations identified; exact-head execution pending**

Load-bearing mutations for this slice:

1. Resume a child before assigning it to the Job Object: the suspended-assignment
   contract fails.
2. Remove kill-on-close or close the Job Object before termination is proved: the
   close-path and process-tree cleanup contracts fail.
3. Remove process or memory limits: native Job Object contracts fail.
4. Launch without the AppContainer/restricted-token boundary or grant access
   outside the workspace: restricted-launch contracts fail.
5. Accept symlink/reparse workspace escape authority: workspace-denial proof fails.
6. Remove product-side output caps or leave descendants alive after timeout:
   ToolHost and native process-tree contracts fail.
7. Inherit parent credentials or accept an unreviewed application environment
   value: environment contracts fail.
8. Change a staged runtime object after the lifetime guard is established: the
   runtime guard rejects.
9. Add a `kaliv_dev_control` import to a product module: workflow coverage rejects.
10. Activate `windows_bounded_subprocess_contract.py`,
    `windows_catalog_tier_a_contract.py` or
    `windows_tier_a_receipt_contract.py` before their dependencies land: workflow
    coverage rejects.
11. Add the source-branch `cryptography` dependency in DC-L05: provenance and scope
    checks reject the later-slice dependency.
12. Populate the DevControl catalog or register a product route: existing dormant
    catalog and repository boundary regressions fail.

The final candidate must run the product-side native contracts on a real Windows
kernel and all portable repository workflows on the same exact head.
