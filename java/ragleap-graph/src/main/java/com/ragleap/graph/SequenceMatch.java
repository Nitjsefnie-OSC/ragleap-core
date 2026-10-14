package com.ragleap.graph;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Port of Python's difflib.SequenceMatcher(None, a, b).ratio() for strings (compared by code point), with the
 * default autojunk behaviour: in the second string, characters that occur very often are ignored when searching
 * for the longest match, once that string has 200 or more characters. There is no isjunk function, so no element
 * is "junk", only "popular".
 */
final class SequenceMatch {
    private SequenceMatch() {
    }

    static double ratio(String a, String b) {
        int[] x = a.codePoints().toArray();
        int[] y = b.codePoints().toArray();
        int length = x.length + y.length;
        if (length == 0) {
            return 1.0;
        }
        return 2.0 * matches(x, y) / length;
    }

    private static int matches(int[] a, int[] b) {
        Map<Integer, List<Integer>> b2j = new LinkedHashMap<>();
        for (int j = 0; j < b.length; j++) {
            b2j.computeIfAbsent(b[j], k -> new ArrayList<>()).add(j);
        }
        int n = b.length;
        if (n >= 200) {
            int ntest = n / 100 + 1;
            b2j.values().removeIf(idxs -> idxs.size() > ntest);
        }
        List<int[]> queue = new ArrayList<>();
        queue.add(new int[] {0, a.length, 0, b.length});
        int total = 0;
        while (!queue.isEmpty()) {
            int[] q = queue.remove(queue.size() - 1);
            int[] m = longest(a, b, b2j, q[0], q[1], q[2], q[3]);
            int i = m[0];
            int j = m[1];
            int k = m[2];
            if (k > 0) {
                total += k;
                if (q[0] < i && q[2] < j) {
                    queue.add(new int[] {q[0], i, q[2], j});
                }
                if (i + k < q[1] && j + k < q[3]) {
                    queue.add(new int[] {i + k, q[1], j + k, q[3]});
                }
            }
        }
        return total;
    }

    /** find_longest_match(alo, ahi, blo, bhi): the earliest-in-a, then earliest-in-b longest block. */
    private static int[] longest(int[] a, int[] b, Map<Integer, List<Integer>> b2j, int alo, int ahi, int blo,
            int bhi) {
        int besti = alo;
        int bestj = blo;
        int bestsize = 0;
        Map<Integer, Integer> j2len = new HashMap<>();
        for (int i = alo; i < ahi; i++) {
            Map<Integer, Integer> newj2len = new HashMap<>();
            List<Integer> js = b2j.get(a[i]);
            if (js != null) {
                for (int j : js) {
                    if (j < blo) {
                        continue;
                    }
                    if (j >= bhi) {
                        break;
                    }
                    int k = j2len.getOrDefault(j - 1, 0) + 1;
                    newj2len.put(j, k);
                    if (k > bestsize) {
                        besti = i - k + 1;
                        bestj = j - k + 1;
                        bestsize = k;
                    }
                }
            }
            j2len = newj2len;
        }
        // Extend the match over equal elements on both sides (this also covers "popular" elements).
        while (besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1]) {
            besti--;
            bestj--;
            bestsize++;
        }
        while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] == b[bestj + bestsize]) {
            bestsize++;
        }
        return new int[] {besti, bestj, bestsize};
    }
}
