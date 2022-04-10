# An experiment in fuzzy matching, using SQL, with CockroachDB

Inspired by a tweet (see below) about the need for _fuzzy matching_, I thought
that we could combine some of the existing capabilities of CockroachDB to
deliver something in a short time.  Note the key features mentioned in the
tweet:

* _similar but not equal sport events names_: a common pattern.  Users tend to mis-type
data in input fields, and data isn't always correct.  Nevertheless, we'd like to return
the closest match.

* _I'd rather use this in-built feature than pay for a whole ES cluster with
added maintenance overhead to boot._: This is the second time I've heard this sentiment
in the past couple of months.  [ES](https://www.elastic.co/) is a full-featured search
engine and delivers a great experience but, for this purpose, would be overkill and
would require additional time and expense to deploy and operate.

![tweet from April 8, 2022](./images/trigram_tweet_2022.04.08.png)

## Background

To begin with, CockroachDB isn't a fork of PostgreSQL, so you don't simply "bolt on"
the usual Postgres extensions such as `pg_trgm`, the module mentioned in the tweet.  But
this is a small obstacle and, in fact, offers the opportunity to demonstrate an up-and-coming
feature of CockroachDB
[_Enterprise Changefeeds_](https://www.cockroachlabs.com/docs/stable/create-changefeed.html),
aka "CDC": the ability to configure a changefeed on a specific _column family_.  This feature
is available in the `v22.1.0-beta.1` version I am using here -- this release should be
generally available by mid-May 2022.

## The experiment

### Desired state

We do INSERT, UPDATE, DELETE on data about sports teams and would like to retrieve
this data based on queries where we may misspell names.  I confess to having misread the tweet,
interpreting it as pertaining to _sports team names_ as opposed to _sport events names_, so what
I show here uses team name data, but I think it's easy to apply to event names as well, so long
as you have access to that data.

### How / what

If we envision the requirement arises out of an application's need to perform this type
of matching, we can build a simple REST app which will:

1. Provide a webhook endpoint to which CockroachDB changefeeds will send events
1. Provide a REST endpoint for _search_, returning a ranked list of the top-N closest team name matches

Here's a first try at the DDL for a very simple table, the only table we'll need:
```sql
CREATE TABLE teams
(
  id UUID PRIMARY KEY DEFAULT GEN_RANDOM_UUID()
  , name TEXT NOT NULL
  , grams TEXT[]
  , FAMILY f1 (id, name)
  , FAMILY f2 (grams)
);
```

And here's the inverted index on the `grams` column:
```sql
CREATE INDEX ON teams USING GIN (grams);
```

Now, we need the REST app.  I use Python for this since it's concise and easy to get up and running,
and the Flask module works very well for REST apps.  And, I had some code fragments hanging around
which I could reuse pretty easily.  The entire Python script [is here](./trigrams.py), but I'll
focus on intersting aspects below.

* Generating n-grams from strings:
```python
def get_ngrams(s, n=3):
  return [s[i:i+n] for i in range(len(s) - n+1)]
```

For the input `la galaxy`, the return value is `['la ', 'a g', ' ga', 'gal', 'ala', 'lax', 'axy']`.
The default value of `n` is 3, which aligns with the way `pg_trgm` works.

A couple of things to point out:
1. The text is lower case.  This is common in information retrieval applications, since all comparisons
are typically done without regard to case.
1. The ngrams show the result of sliding a window across the string, from left to right, yielding
3-character sequences which can span the space between words.  This latter aspect factors in the
adjacent words, so phrases are scored appropriately.



## The more general pattern

## Acknowledgements

The author wishes to thank the following individuals for providing valuable input which made this blog
post possible:

* Dan Kelly, for mentioning the tweet which inspired the activity focused on n-grams
* `@schrepfler`, for tagging `@CockroachDB` in the tweet about n-grams and fuzzy matching
* Aaron Zinger, for a heads up about the upcoming changefeed support for column families
* Rebecca Taft, for pushing on the PR for index acceleration of the `&&` operator
* Rajiv Sharma, for providing that PR and for adding the final polish to it yesterday, so it could be merged
* Jordan Lewis, for [taking up the trigram cause in the core of CockroachDB itself](https://m.twitch.tv/videos/1450106719)

## Reference

* [The tweet](https://twitter.com/schrepfler/status/1512434401652654085)
* [GIN (index) acceleration for `&&` operator](https://github.com/cockroachdb/cockroach/pull/77418)
* [Data](https://en.wikipedia.org/wiki/List_of_professional_sports_teams_in_the_United_States_and_Canada)
* [CockroachDB downloads](https://www.cockroachlabs.com/docs/releases/index.html)
* [The `pg_trgm` module](https://www.postgresql.org/docs/current/pgtrgm.html)
* [Hot Fuzz (film)](https://www.rottentomatoes.com/m/hot_fuzz)

