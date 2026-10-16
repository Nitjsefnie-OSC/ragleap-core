package com.ragleap.graph;

import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;

/**
 * Turns a libpq connection URI (postgresql://user:password@host:port/dbname?params) into a JDBC URL plus user and
 * password. Only the URI form is supported; the query string is passed on as it is, so parameters both libpq and the
 * PostgreSQL JDBC driver know (such as sslmode) work, libpq-only ones may not.
 */
final class LibpqUrl {
    record Target(String jdbcUrl, String user, String password) {
    }

    private LibpqUrl() {
    }

    static Target parse(String url) {
        if (url == null) {
            throw new IllegalArgumentException("connection string is null");
        }
        URI uri;
        try {
            uri = new URI(url);
        } catch (URISyntaxException e) {
            throw new IllegalArgumentException("not a valid connection URI: " + e.getReason());
        }
        String scheme = uri.getScheme();
        if (!"postgresql".equals(scheme) && !"postgres".equals(scheme)) {
            throw new IllegalArgumentException("only postgresql:// connection URIs are supported");
        }
        String hostPort = uri.getRawAuthority() == null ? "" : uri.getRawAuthority();
        String userInfo = null;
        int at = hostPort.lastIndexOf('@');
        if (at >= 0) {
            userInfo = hostPort.substring(0, at);
            hostPort = hostPort.substring(at + 1);
        }
        String host;
        int port = 5432;
        if (hostPort.startsWith("[")) {
            int close = hostPort.indexOf(']');
            if (close < 0) {
                throw new IllegalArgumentException("unterminated IPv6 address");
            }
            host = hostPort.substring(0, close + 1);
            String rest = hostPort.substring(close + 1);
            if (rest.startsWith(":") && rest.length() > 1) {
                port = Integer.parseInt(rest.substring(1));
            }
        } else {
            int colon = hostPort.lastIndexOf(':');
            if (colon >= 0) {
                host = hostPort.substring(0, colon);
                if (colon + 1 < hostPort.length()) {
                    port = Integer.parseInt(hostPort.substring(colon + 1));
                }
            } else {
                host = hostPort;
            }
        }
        if (host.isEmpty()) {
            host = "localhost";
        }
        String user = null;
        String password = null;
        if (userInfo != null) {
            int colon = userInfo.indexOf(':');
            if (colon >= 0) {
                user = percentDecode(userInfo.substring(0, colon));
                password = percentDecode(userInfo.substring(colon + 1));
            } else {
                user = percentDecode(userInfo);
            }
        }
        String path = uri.getRawPath() == null ? "" : uri.getRawPath();
        String db = path.startsWith("/") ? path.substring(1) : path;
        String query = uri.getRawQuery();
        String jdbc = "jdbc:postgresql://" + host + ":" + port + "/" + db + (query != null ? "?" + query : "");
        return new Target(jdbc, user, password);
    }

    /** Percent-decoding only: a plus sign stays a plus sign. */
    private static String percentDecode(String s) {
        return URLDecoder.decode(s.replace("+", "%2B"), StandardCharsets.UTF_8);
    }
}
