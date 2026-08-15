package xyz.xingfeng.QuanForge.exception;

import org.hibernate.exception.ConstraintViolationException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.orm.jpa.JpaSystemException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 全局异常处理：将常见异常映射为标准 HTTP 状态码与 ProblemDetail（RFC 7807）。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

	/** 资源不存在 → 404 */
	@ExceptionHandler(NotFoundException.class)
	public ProblemDetail handleNotFound(NotFoundException e) {
		return ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, e.getMessage());
	}

	/** 请求体校验失败 → 400 */
	@ExceptionHandler(MethodArgumentNotValidException.class)
	public ProblemDetail handleValidation(MethodArgumentNotValidException e) {
		FieldError fieldError = e.getBindingResult().getFieldError();
		String detail = fieldError != null
				? fieldError.getField() + ": " + fieldError.getDefaultMessage()
				: "请求参数校验失败";
		return ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, detail);
	}

	/** 删除不存在的资源 → 404 */
	@ExceptionHandler(EmptyResultDataAccessException.class)
	public ProblemDetail handleEmptyResult(EmptyResultDataAccessException e) {
		return ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, "资源不存在");
	}

	/** 唯一约束冲突（如凭证名重复）→ 409 */
	@ExceptionHandler(DataIntegrityViolationException.class)
	public ProblemDetail handleDataIntegrity(DataIntegrityViolationException e) {
		return ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, "数据冲突，可能存在重复值");
	}

	/**
	 * JPA 系统异常（SQLite 唯一约束冲突在事务提交/刷新阶段经 Hibernate 包装为此异常，
	 * 不会走 DataIntegrityViolationException）→ 约束冲突返回 409，其余为 500。
	 */
	/**
	 * JPA 系统异常（SQLite 唯一约束冲突在事务提交/刷新阶段经 Hibernate 包装为此异常，
	 * 不会走 DataIntegrityViolationException）→ 约束冲突返回 409，其余为 500。
	 */
	@ExceptionHandler(JpaSystemException.class)
	public ProblemDetail handleJpaSystem(JpaSystemException e) {
		// 兼容两种包装：Hibernate 的 ConstraintViolationException，或
		// SQLite 方言的 GenericJDBCException -> SQLiteException（根因消息含 UNIQUE constraint）
		Throwable cause = e;
		while (cause != null) {
			if (cause instanceof ConstraintViolationException) {
				return ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, "数据冲突，可能存在重复值");
			}
			cause = cause.getCause();
		}
		String rootMessage = String.valueOf(e.getMostSpecificCause().getMessage());
		if (rootMessage.toLowerCase().contains("unique constraint")) {
			return ProblemDetail.forStatusAndDetail(HttpStatus.CONFLICT, "数据冲突，可能存在重复值");
		}
		return ProblemDetail.forStatusAndDetail(HttpStatus.INTERNAL_SERVER_ERROR, "数据库操作失败");
	}
}
