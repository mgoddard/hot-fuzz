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

If we envision the requirement arises out of an application's need to perform this type
of matching, we can build a simple REST app which will:

1. Provide a webhook endpoint to which CockroachDB changefeeds will send events
1. Provide a REST endpoint for _search_, returning a ranked list of the top-N closest team name matches

### DDL for the table

Here's a first try at the DDL for a very simple table, the only table we'll need.
The `FAMILY ...` parts of this enable the changefeed to generate events based solely
on `FAMILY f1`, ignoring the resulting changes to `FAMILY f2`, which is what we need:
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

### REST app: CDC / indexing

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
1. The text is lower cased by a separate Python function.  This is common in information retrieval
applications, since comparisons are typically done without regard to case.
1. The ngrams show the result of sliding a window across the string, from left to right, yielding
3-character sequences which can span the space between words.  This latter aspect factors in the
adjacent words, so phrases are scored appropriately.

* Webhook endpoint for the changefeed:
```python
@app.route('/cdc', methods = ['POST', 'GET'])
def cdc_webhook():
  obj = request.get_json(force=True)
  print("CDC: " + json.dumps(obj)) # DEBUG
  for o in obj["payload"]:
    if o["after"] is None:
      pass # Nothing to be done here
    else:
      pk = o["after"]["id"]
      name = o["after"]["name"]
      index_string(pk, name)
  return "OK", 200
```

The changefeed will send an HTTP POST to this `/cdc` endpoint, as configured via the SQL expression
(see below).  When that happens, JSON is accessible by the call to `request.get_json(force=True)`,
and that JSON contains the current values of the `id` and `name` columns from the `teams` table.

* Those values are passed to the `index_string(pk, name)` function, which just updates the `grams`
colunn of the `teams` table:
```python
def index_string(pk, content):
  ng = tokenize(content)
  stmt = text("UPDATE teams SET grams = :grams WHERE id = :pk").bindparams(grams=ng, pk=pk)
  run_statement(stmt)
```

I won't get into the `run_statement(stmt)` function here, but will instead refer interested readers
to the code itself.

* Here is the SQL statement we need to run to configure the changefeed, tying all of this together:
```sql
CREATE CHANGEFEED FOR TABLE teams FAMILY "f1"
INTO 'webhook-https://localhost:18080/cdc?insecure_tls_skip_verify=true'
WITH updated, full_table_name, topic_in_value;
```
Note that this operation requires an
[Enterprise License](https://www.cockroachlabs.com/docs/v21.2/licensing-faqs#obtain-a-license),
though I will make it a TODO to try this out on [CockroachDB Serverless](https://cockroachlabs.cloud/signup)
as soon as the 22.1 release is available there.

### REST app: search / fuzzy matching

A REST client can retrieve fuzzy matches for a given team name by doing something
equivalent to this (this example was run on my MacBook; the `base64` command works
differently here than it does on Linux; `pretty_print_json.py` is [here](./pretty_print_json.py)):
```bash
$ name="PA Galuxy"; time curl -k -s https://localhost:18080/search/$( echo -n $name | base64 )/5 | pretty_print_json.py 
[
  {
    "name": "LA Galaxy",
    "pk": "15e240a7-d1db-4b77-b454-c895a11610bf",
    "score": "42.8571"
  },
  {
    "name": "LA Galaxy II",
    "pk": "85b5b97a-9a6e-4cef-b63c-7cbe123eca07",
    "score": "10.7143"
  },
  {
    "name": "LA Giltinis",
    "pk": "82b96763-6836-4ab8-84ad-1864a1f3e16d",
    "score": "4.7619"
  },
  {
    "name": "Tampa Mayhem",
    "pk": "6f5fd5e0-6654-4385-9bd0-c191f4f1c5b4",
    "score": "3.5714"
  },
  {
    "name": "Tampa Tarpons",
    "pk": "1851c8e9-77e8-456b-a197-6aaed971942a",
    "score": "2.8571"
  }
]

real	0m0.196s
user	0m0.063s
sys	0m0.043s
```

Before getting into the Python code for the `/search` endpoint, the following are worthy of mention:
1. I deliberately misspelled the name of the team; "LA Galaxy" was the one I wanted.
1. Even though the initial character, the 'P' in "PA Galuxy", was incorrect, the results were correct.
This is one of the essential features of n-gram based matching -- you don't rely on the leading
characters in the string to match.

On to the Python part of this interaction:
```python
@app.route("/search/<q_base_64>/<int:limit>")
def do_search(q_base_64, limit):
  query_str = decode(q_base_64)
  logging.info("Query: {}".format(query_str))
  ng = tokenize(query_str)
  logging.info("Query (n-grams): {}".format(ng))
  sql = """
  WITH qbool AS
  (
    SELECT id, grams, 1 + ABS(ARRAY_LENGTH(grams, 1) - ARRAY_LENGTH(CAST(:ngrams AS TEXT[]), 1)) delta
    FROM teams
    WHERE grams && CAST(:ngrams AS TEXT[])
  ), qscore AS
  (
    SELECT id, COUNT(*) n FROM
    (
      SELECT id, UNNEST(grams) FROM qbool
      INTERSECT
      SELECT id, UNNEST(CAST(:ngrams AS TEXT[])) FROM qbool
    )
    GROUP BY id
  )
  SELECT qbool.id, t.name, 100*n/delta score
  FROM qbool, qscore, teams t
  WHERE qbool.id = qscore.id AND t.id = qbool.id
  ORDER BY score DESC
  LIMIT :max_rows;
  """
  stmt = text(sql).bindparams(ngrams=ng, max_rows=limit)
  rv = []
  for row in run_statement(stmt, True, False):
    pk = str(row[0])
    name = str(row[1])
    score = float(row[2]/len(ng))
    d = {}
    (d["pk"], d["name"], d["score"]) = (pk, name, '{:.4f}'.format(score))
    rv.append(d)
  return Response(json.dumps(rv), status=200, mimetype="application/json")
```

There's a fair bit going on here, mostly within the SQL expresssion.  I'll do my best
to narrate that:
* There are two common table expressions (CTEs) which handle different aspects
* `qbool` handles the boolean nature: is this row a match or not?  It also provides
an additional scoring input, which is the difference in the length of the provided
query string and the actual value in the `grams` column.  This is used to, for example,
boost the score for the row containing "LA Galaxy" relative to a row containing "LA Galaxy II".
* The query predicate, `WHERE grams && CAST(:ngrams AS TEXT[])`, incorporates the `&&`
(array overlap) operator.  Ideally, this operation would use the GIN index and,
as of [this pull request](https://github.com/cockroachdb/cockroach/pull/77418),
it will.
* `qscore` just uses the results of `qbool` to determine a score based on the number
of overlapping n-grams between the matching row and the query.
* Finally, the results of these CTEs are combined with the `name` column from the
`teams` table to generate an ordered result to return to the client in JSON
format (see the above example).

## An emerging pattern?

What I find interesting about this exercise is that this pattern of configuring a
changefeed to route events through an external system, then back into the database
has enormous potential, far beyond this fuzzy matching example.  It seems that
development practices have evolved away from burying logic in the database and
towards coding it in the languages most applicable to the problem; the emergence
of microservices aligns with this trend.  That observation, combined with this
new feature of being able to define a changefeed on a specific column family, has
me convinced we'll see some very interesting applications of this pattern with
CockroachDB.

## The HOWTO

Here are some notes on how to replicate what I've shown above.  Given I've already done
this, it's possible I'll leave out some step, so please let me know (GitHub issue is
probably the simplest way).  I'm going to illustrate this using an Ubuntu VM I've just
deployed in Google Cloud Platform.

* Install some prereq's (I like to use the `psql` CLI):
```bash
sudo apt install postgresql-client-common
sudo apt install postgresql-client
```

* Deploy the latest CockroachDB binary (I'll use the beta since 22.1 hasn't yet shipped):
```bash
$ curl https://binaries.cockroachdb.com/cockroach-v22.1.0-beta.1.linux-amd64.tgz | tar xzvf -
```

* Then start "demo" mode:
```bash
$ ./cockroach-v22.1.0-beta.1.linux-amd64/cockroach demo
```
In the output, you'll see a line like the following, which you'll use in a couple of contexts:
step:
```
#     (sql)      postgresql://demo:demo15932@127.0.0.1:26257/movr?sslmode=require
```

* Clone this GitHub repo:
```bash
$ git clone https://github.com/mgoddard/hot-fuzz.git
```

* Make that repo your current working directory (the VM's hostname is also `hot-fuzz`):
```bash
mgoddard@hot-fuzz:~$ cd hot-fuzz/
mgoddard@hot-fuzz:~/hot-fuzz$ ls
LICENSE  README.md  images  prep_teams_data.pl  pretty_print_json.py  trigrams.py
mgoddard@hot-fuzz:~/hot-fuzz$
```

* Start up the Python Flask REST app:
```bash

```

* Load the data (the Perl script is included in this repo):
```bash
curl -s https://en.wikipedia.org/wiki/List_of_professional_sports_teams_in_the_United_States_and_Canada | ./prep_teams_data.pl | psql postgres://root@localhost:26257/defaultdb
```

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
* [Hot Fuzz (film) provided the name for this repo](https://www.rottentomatoes.com/m/hot_fuzz)

