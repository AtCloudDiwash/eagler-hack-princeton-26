# Security and Environment Configuration

### .env Files

- Create a `.env` file in the `backend/` directory by copying `.env.example`.
- Example content of `.env.example`:
  ```
  COSTAR_API_KEY=your_costar_key_here
  MATTERPORT_API_KEY=your_matterport_key_here
  VEXCEL_API_KEY=your_vexcel_key_here
  GEOCODING_API_KEY=your_geocoding_key_here
  ANTHROPIC_API_KEY=your_anthropic_key_here
  ```

- The frontend Next.js app should not contain real secret keys. Only put non-sensitive configs in `NEXT_PUBLIC_` variables if needed. (E.g., `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` if used for a map tile.)
- Add `.env` and any private key files to `.gitignore`. Only commit `.env.example` with placeholders.

### API Keys

- **CoStar**: If you have developer access, store the API key in `COSTAR_API_KEY`. Otherwise, leave blank to use mocks.
- **Matterport**: `MATTERPORT_API_KEY` for embedding (if required). For static images, may not need it.
- **Vexcel Imaging**: `VEXCEL_API_KEY` if using their API.
- **Geocoding**: `GEOCODING_API_KEY` (e.g. Google or Mapbox) if performing live geocode.
- **Anthropic (Claude)**: `ANTHROPIC_API_KEY` if using Claude for any NLP. (This project uses rules, so this may not be needed.)

### Security Practices

- Do not print secrets in logs.
- Use HTTPS endpoints for all API calls.
- CORS: Allow frontend `localhost:3000` to call backend `localhost:8000`.
- Rate-limit calls in the backend if looping over many properties (to avoid accidental DDoS).
- For demo, consider disabling any unsafe operations and use safe defaults.

### Running in Live vs Mock

- By default, the app should run in "mock mode" if keys are missing.
- If `ENV=production` or keys are present, it should attempt real API calls.
- Provide clear console logs about which mode is active.
