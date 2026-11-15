package xyz.xingfeng.QuanForge.paper;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.URI;

/** Paper-only releases cannot reach legacy credential, AI or account endpoints. */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class PaperOnlyFilter extends OncePerRequestFilter {
    private final boolean enabled;
    public PaperOnlyFilter(@Value("${app.paper-only:false}") boolean enabled) { this.enabled=enabled; }

    @Override protected void doFilterInternal(HttpServletRequest req,HttpServletResponse res,FilterChain chain)
            throws ServletException,IOException {
        String path=req.getRequestURI();
        if (enabled && path.startsWith("/api/") && !(path.equals("/api/runtime") ||
                path.equals("/api/paper/status") || path.equals("/api/paper/control") || path.equals("/api/paper/proxy"))) {
            reject(res,403,"PAPER_ONLY","当前版本仅提供纸面研究功能");return;
        }
        if (enabled && !req.getMethod().equals("GET") && !req.getMethod().equals("HEAD")) {
            String origin=req.getHeader("Origin");
            if (origin!=null) {
                try {
                    URI uri=URI.create(origin);
                    if (!uri.getRawAuthority().equalsIgnoreCase(req.getHeader("Host"))) {
                        reject(res,403,"ORIGIN_MISMATCH","请求来源不匹配");return;
                    }
                } catch (RuntimeException e) { reject(res,403,"ORIGIN_MISMATCH","请求来源不匹配");return; }
            }
        }
        chain.doFilter(req,res);
    }
    private void reject(HttpServletResponse res,int status,String code,String message) throws IOException {
        res.setStatus(status);res.setCharacterEncoding("UTF-8");res.setContentType("application/json");
        res.getWriter().write(new org.json.JSONObject().put("code",code).put("message",message).toString());
    }
}
