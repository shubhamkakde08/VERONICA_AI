-- ReportBot's own tables (created automatically on first start; this file is for DBAs).
-- CREATE DATABASE reportbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE rb_messages (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	chat_key VARCHAR(80) NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rb_roles (
	name VARCHAR(50) NOT NULL, 
	description VARCHAR(255), 
	allowed_tables JSON NOT NULL, 
	can_teach BOOL, 
	can_schedule BOOL, 
	free_query BOOL, 
	is_admin BOOL, 
	PRIMARY KEY (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rb_skill_versions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	skill_name VARCHAR(60) NOT NULL, 
	version INTEGER NOT NULL, 
	snapshot JSON NOT NULL, 
	changed_by VARCHAR(100), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (skill_name, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rb_skills (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(60) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT, 
	rules TEXT, 
	output_format TEXT, 
	default_formats VARCHAR(100), 
	sql_template TEXT, 
	example_output TEXT, 
	allowed_roles JSON, 
	version INTEGER, 
	created_by VARCHAR(100), 
	updated_at DATETIME, 
	active BOOL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rb_users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL, 
	`role` VARCHAR(50) NOT NULL, 
	telegram_id VARCHAR(32), 
	web_token VARCHAR(64), 
	active BOOL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(`role`) REFERENCES rb_roles (name), 
	UNIQUE (telegram_id), 
	UNIQUE (web_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rb_reports (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER, 
	channel VARCHAR(20), 
	skill_name VARCHAR(60), 
	title VARCHAR(200), 
	request_text TEXT, 
	sql_text TEXT, 
	row_count INTEGER, 
	summary TEXT, 
	files JSON, 
	data_preview JSON, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES rb_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE rb_schedules (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL, 
	skill_name VARCHAR(60) NOT NULL, 
	cron VARCHAR(100) NOT NULL, 
	prompt TEXT, 
	formats VARCHAR(100), 
	target_chat_id VARCHAR(32) NOT NULL, 
	owner_user_id INTEGER, 
	active BOOL, 
	last_run_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_user_id) REFERENCES rb_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
