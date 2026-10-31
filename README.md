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

## Important production deployment steps

1. Copy `.env.example` to `.env`.
2. Generate a random `SECRET_KEY` of at least 32 characters.
3. Set the real MongoDB URI and credentials.
4. Set `FRONTEND_ORIGINS=https://aifaceattendanceui.mssplonline.in`.
5. Change `SEED_ADMIN_PASSWORD` from the development value.
6. Run the seed script once:
   `python -m scripts.seed_admin`
7. Put TLS termination in Nginx/Caddy/your cloud load balancer.
8. Do not expose MongoDB publicly.
9. Persist `/app/data` securely and back it up.
10. For GPU inference, use a tested CUDA/ONNX Runtime image and `requirements-gpu.txt` rather than installing GPU packages blindly on the CPU image.

## FAISS

The current search layer uses MongoDB embeddings so the system remains simple to deploy. The `Recognizer` search loop is the intended replacement point for FAISS. Adding FAISS later should not change the API or attendance layer.

## Your requested test account

For the initial setup only, create the requested account with:



Do not keep this password in a production `.env`; change it immediately after first deployment.
