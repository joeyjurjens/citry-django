# Security policy

## Reporting a vulnerability

Report a vulnerability privately. Do not open a public issue or pull
request for it.

1. Open the Security tab of the repository at
   <https://github.com/joeyjurjens/citry-django> and choose **Report a
   vulnerability**. Only the maintainer can read the report.
2. If that button is not there, email joeyjurjens@gmail.com and put
   "citry-django security" in the subject line.

If the problem is in Citry or Django itself rather than in this
repository's packages, report it to that project instead.

## What to include

- The package (`citry-django`, `citry-django-compressor`, or
  `citry-django-djc`) and its version.
- Your Python, Django, and Citry versions.
- What you found, and what an attacker can do with it.
- The smallest template, component, or request that shows it.
- A fix, if you have one in mind.
- Whether anyone else knows about it yet.

Leave out real secrets and real user data. A harmless test value is enough
to show the problem.

## What to expect

<!-- Maintainer: confirm both numbers, then delete this comment. -->

The maintainer aims to reply to a report within [PLACEHOLDER: number of
days], and to say within [PLACEHOLDER: number of days] whether it is
accepted and when a fix is likely.

## Supported versions

Only the latest minor release of each package gets security fixes. A fix
ships as a patch release of that line. If you run an older minor release,
upgrade to the latest one.
