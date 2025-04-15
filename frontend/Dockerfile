FROM node:16-alpine

WORKDIR /app

# Copy package.json and package-lock.json
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy project files
COPY . .

# Build app for production
RUN npm run build

# Install serve to run the application
RUN npm install -g serve

# Command to run when container starts
CMD ["serve", "-s", "build", "-l", "3000"] 