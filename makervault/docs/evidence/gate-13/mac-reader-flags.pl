# Read-only system-root flag matrix; no files created or application data read.
use strict;
use warnings;
for my $probe (['base', 0x01100000], ['nofollow', 0x01100100],
               ['nofollow-any', 0x21100000], ['both', 0x21100100]) {
    my ($label, $flags) = @$probe;
    my $opened = sysopen(my $handle, '/', $flags);
    printf "anchor-flag=%s opened=%d errno=%d\n", $label, $opened ? 1 : 0, $opened ? 0 : 0 + $!;
    close($handle) if $opened;
}
