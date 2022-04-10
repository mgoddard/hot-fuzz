#!/usr/bin/env perl

while (<>)
{
  if (m~<td><b><a href="/wiki/[^"]+" title="([^"]+)">[^<]+</a></b>~) {
    $name = $1;
    $name =~ s/ *\(.+$//g;
    print "INSERT INTO teams (name) VALUES ('$name');\n";
  }
}

