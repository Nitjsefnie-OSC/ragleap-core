package com.ragleap.vectorstores;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.net.ssl.SSLSocketFactory;

/**
 * A minimal Redis client speaking RESP2 over one socket (no vendor SDK): commands are arrays of bulk strings,
 * replies come back as String (simple string), Long (integer), byte[] (bulk string), List (array) or null; an error
 * reply throws SQLException. The connection is opened on the first command (redis-py does the same). Supports
 * redis:// and rediss:// urls with optional user and password and a database number; anything after "?" is ignored.
 * Not covered by the parity tests: authentication, database selection and TLS.
 */
final class RespClient implements AutoCloseable {
    private final String host;
    private final int port;
    private final boolean tls;
    private final String user;
    private final String password;
    private final int db;
    private Socket socket;
    private InputStream in;
    private OutputStream out;

    RespClient(String url) {
        boolean secure;
        String rest;
        if (url.startsWith("redis://")) {
            secure = false;
            rest = url.substring(8);
        } else if (url.startsWith("rediss://")) {
            secure = true;
            rest = url.substring(9);
        } else {
            throw new IllegalArgumentException("unsupported redis url (use redis:// or rediss://): " + url);
        }
        int q = rest.indexOf('?');
        if (q >= 0) {
            rest = rest.substring(0, q);
        }
        int slash = rest.indexOf('/');
        String hostPart = slash < 0 ? rest : rest.substring(0, slash);
        String path = slash < 0 ? "" : rest.substring(slash + 1);
        String u = null;
        String pw = null;
        int at = hostPart.lastIndexOf('@');
        if (at >= 0) {
            String info = hostPart.substring(0, at);
            hostPart = hostPart.substring(at + 1);
            int colon = info.indexOf(':');
            if (colon >= 0) {
                u = info.substring(0, colon);
                pw = info.substring(colon + 1);
            } else {
                u = info;
            }
            u = u == null || u.isEmpty() ? null : decode(u);
            pw = pw == null ? null : decode(pw);
        }
        String h;
        int p = 6379;
        if (hostPart.startsWith("[")) {
            int end = hostPart.indexOf(']');
            h = hostPart.substring(1, end);
            String r = hostPart.substring(end + 1);
            if (r.startsWith(":")) {
                p = Integer.parseInt(r.substring(1));
            }
        } else {
            int colon = hostPart.lastIndexOf(':');
            if (colon >= 0) {
                h = hostPart.substring(0, colon);
                p = Integer.parseInt(hostPart.substring(colon + 1));
            } else {
                h = hostPart;
            }
        }
        this.host = h.isEmpty() ? "localhost" : h;
        this.port = p;
        this.tls = secure;
        this.user = u;
        this.password = pw;
        this.db = path.isEmpty() ? 0 : Integer.parseInt(path);
    }

    private static String decode(String s) {
        return URLDecoder.decode(s.replace("+", "%2B"), StandardCharsets.UTF_8);
    }

    /** RESP2 request: an array of bulk strings. */
    static byte[] encode(Object... args) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        o.writeBytes(("*" + args.length + "\r\n").getBytes(StandardCharsets.US_ASCII));
        for (Object a : args) {
            byte[] b = a instanceof byte[] bytes ? bytes : String.valueOf(a).getBytes(StandardCharsets.UTF_8);
            o.writeBytes(("$" + b.length + "\r\n").getBytes(StandardCharsets.US_ASCII));
            o.writeBytes(b);
            o.writeBytes("\r\n".getBytes(StandardCharsets.US_ASCII));
        }
        return o.toByteArray();
    }

    private void connect() throws IOException, SQLException {
        Socket s = tls ? SSLSocketFactory.getDefault().createSocket() : new Socket();
        s.connect(new InetSocketAddress(host, port), 10_000);
        s.setSoTimeout(30_000);
        socket = s;
        in = new BufferedInputStream(s.getInputStream());
        out = s.getOutputStream();
        if (password != null) {
            roundTrip(user != null ? new Object[] {"AUTH", user, password} : new Object[] {"AUTH", password});
        }
        if (db != 0) {
            roundTrip("SELECT", Integer.toString(db));
        }
    }

    private Object roundTrip(Object... args) throws IOException, SQLException {
        out.write(encode(args));
        out.flush();
        return read();
    }

    synchronized Object command(Object... args) throws SQLException {
        try {
            if (socket == null) {
                connect();
            }
            return roundTrip(args);
        } catch (IOException e) {
            closeQuietly();
            throw new SQLException("Redis request failed: " + args[0], e);
        }
    }

    private String readLine() throws IOException {
        StringBuilder sb = new StringBuilder();
        int b;
        while ((b = in.read()) >= 0) {
            if (b == '\r') {
                if (in.read() != '\n') {
                    throw new IOException("malformed RESP line");
                }
                return sb.toString();
            }
            sb.append((char) b);
        }
        throw new EOFException();
    }

    private Object read() throws IOException, SQLException {
        int t = in.read();
        if (t < 0) {
            throw new EOFException();
        }
        String line = readLine();
        switch (t) {
            case '+':
                return line;
            case '-':
                throw new SQLException("Redis error: " + line);
            case ':':
                return Long.parseLong(line);
            case '$': {
                int n = Integer.parseInt(line);
                if (n < 0) {
                    return null;
                }
                byte[] b = in.readNBytes(n);
                if (b.length < n || in.readNBytes(2).length < 2) {
                    throw new EOFException();
                }
                return b;
            }
            case '*': {
                int n = Integer.parseInt(line);
                if (n < 0) {
                    return null;
                }
                List<Object> l = new ArrayList<>();
                for (int i = 0; i < n; i++) {
                    l.add(read());
                }
                return l;
            }
            default:
                throw new IOException("unexpected RESP type " + (char) t);
        }
    }

    private void closeQuietly() {
        try {
            if (socket != null) {
                socket.close();
            }
        } catch (IOException ignored) {
            // nothing to do
        }
        socket = null;
    }

    @Override
    public synchronized void close() {
        closeQuietly();
    }
}
