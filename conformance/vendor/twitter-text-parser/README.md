# Parser compatibility edition

The app uses the MIT Python port `twitter-text-parser`3.0.0, relocated as
`content_strategy.vendor.twitter_text`, compatibility edition
`3.0.0+stdlib.resources.1`. PROVENANCE.json records all38 original/derived member
hashes; resource-loader.patch contains exactly five changed lines in two files.
Three imports become relative and two resource-loading lines use the Python
standard library. Parsing algorithms, configuration and emoji data are unchanged.
The complete MIT notice is retained here and beside the vendored package.

The separately licensed official Twitter vectors retain their Apache-2.0 LICENSE
and README under `../twitter-text-official/`, pinned to commit
`65e7e00da383fb77f5ab7fe3c0dc26b724e14035`.

`tests/platforms/test_x_parser.py` reads the original YAML dynamically. The required
mapped profile covers weighted v3 emoji counting, Unicode directional markers,
URL strings, directional URL objects with indices, t.co query parameters, URL
indices and every supplied TLD group:1,706 official cases. It also contains eight
synthetic ASCII/CJK/emoji/invalid-character boundary cases and one member/license
integrity control. No original case, text or expected value is altered.

Legacy v1/v2 validation, mention/list/hashtag and non-URL extraction APIs are outside
this app's target-weight profile. Passing this profile does not certify the entire
upstream library, model judgment quality, a platform publishing integration or the
finished application. The app supports standard X weighted validity and length;
it does not publish posts or support paid long-form post limits.
