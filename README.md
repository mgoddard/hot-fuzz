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

## Reference

* [The tweet](https://twitter.com/schrepfler/status/1512434401652654085)
* [GIN (index) acceleration for `&&` operator](https://github.com/cockroachdb/cockroach/pull/77418)
* [The film](https://www.rottentomatoes.com/m/hot_fuzz)

