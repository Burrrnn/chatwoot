# ---------- BUILD STAGE ----------
FROM ruby:3.4.4-alpine3.21 AS builder

ARG NODE_VERSION=24
ARG PNPM_VERSION=10.2.0
ARG RAILS_ENV=production

ENV RAILS_ENV=${RAILS_ENV}
ENV BUNDLE_PATH=/gems
ENV BUNDLE_WITHOUT="development:test"

# System deps (only what we need to build)
RUN apk add --no-cache \
  build-base \
  git \
  curl \
  openssl \
  tzdata \
  postgresql-dev \
  vips \
  yaml-dev \
  xz

# Install bundler
RUN gem install bundler -v 2.5.16

# Install Node + PNPM
RUN apk add --no-cache nodejs npm
RUN npm install -g pnpm@${PNPM_VERSION}

WORKDIR /app

# 1st cache layer (MOST IMPORTANT)
COPY Gemfile Gemfile.lock ./
RUN bundle install

# 2nd cache layer
COPY package.json pnpm-lock.yaml ./
RUN pnpm install

# App source (only here cache breaks)
COPY . .

# Precompile assets
RUN SECRET_KEY_BASE=dummy bundle exec rake assets:precompile

# cleanup (reduce size)
RUN rm -rf node_modules/.cache tmp cache

# ---------- FINAL IMAGE ----------
FROM ruby:3.4.4-alpine3.21

ENV RAILS_ENV=production
ENV BUNDLE_PATH=/gems

RUN apk add --no-cache \
  postgresql-client \
  tzdata \
  vips \
  imagemagick

# copy ruby gems + app
COPY --from=builder /gems /gems
COPY --from=builder /app /app

WORKDIR /app

EXPOSE 3000

CMD ["bundle", "exec", "rails", "s", "-b", "0.0.0.0", "-p", "3000"]
