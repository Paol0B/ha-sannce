# Security policy

## Supported versions

Only the latest commit on `master` gets fixes.

## Report a vulnerability

Report it privately. Open the repository's **Security** tab and pick **Report a vulnerability** ([how](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)). Do not open a public issue.

Include the commit, the steps to reproduce and the impact. This is a spare-time project: answers are best effort, with no fixed deadline. A fix is announced in a GitHub security advisory once it is on `master`.

## Scope

In scope: the code in this repository and in the library [sannce-aio](https://github.com/Paol0B/sannce-aio).

Out of scope:

- Flaws in the camera firmware or the vendor's apps. Report those to the vendor.
- The camera protocol's lack of encryption. It is a known limit of the camera, see [Security](README.md#security) in the README.
