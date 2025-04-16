# --- Build Stage ---
FROM node:16-alpine AS build
# Set working directory
WORKDIR /app
# Copy package files and install dependencies using 'ci' for reproducibility
COPY package*.json ./
RUN npm ci
# Copy source code and build the React application
COPY . .
RUN npm run build

# --- Production Stage ---
# Use a specific Nginx version
FROM nginx:1.25-alpine
# Copy the built static files from the build stage
COPY --from=build /app/build /usr/share/nginx/html
# Copy the custom Nginx configuration
# This file needs to exist in the frontend directory context
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Expose port 80 for Nginx
EXPOSE 80
# Default command to start Nginx
CMD ["nginx", "-g", "daemon off;"]