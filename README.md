# VertexFace AI Attendance Backend — Production Baseline

FastAPI + MongoDB + InsightFace backend matching the supplied `faceAttViteUI` frontend.

## Supported frontend endpoints

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/signup`
- `GET /api/v1/auth/me`
- `GET /api/v1/dashboard/`
- `GET /attendance`
- `GET /api/v1/attendance/today`
- `GET /api/v1/attendance/me/today`
- `GET /employees`
- `GET /employees/{id}`
- `DELETE /employees/{id}`
- `GET /register/users`
- `POST /register/register-employee`
- `POST /recognize/`
- `GET/POST /cameras`
- `PUT/DELETE /cameras/{id}`
- `GET/POST /api/v1/organization/departments`
- `GET/POST /api/v1/organization/designations`
- `GET /api/v1/policies`
- `POST /api/v1/policies`
- `PUT /api/v1/policies/{policy_id}/assign/{user_id}`

## Attendance model

One camera is used for both entry and exit. Each recognition toggles the employee's daily state:

`OUT -> IN -> OUT -> IN -> OUT`

A day contains multiple sessions. Raw timestamps are preserved. Working minutes are accumulated from closed IN/OUT sessions.

## Security

- Argon2 password hashes
- JWT access tokens
- Role + permission authorization
- Production CORS allowlist
- Upload size limit
- Image type validation
- Exactly one face during registration/recognition
- Face quality checks during registration
- Duplicate face check during registration
- MongoDB indexes
- Inactive users cannot authenticate


