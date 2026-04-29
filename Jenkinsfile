@Library('routebox-shared@main') _

// route-optimizer deploy pipeline.
//
// Same shape as the other apps. The weekly-restart Jenkins job
// (resources/jobs/route-optimizer-weekly-restart.groovy in routebox-jenkins)
// runs separately on a Sunday cron and is unrelated to this pipeline.
// Don't disable that job. See README.

pipeline {

    agent { label 'docker' }

    options {
        timestamps()
        ansiColor('xterm')
        timeout(time: 60, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '50'))
        disableConcurrentBuilds()
    }

    environment {
        SERVICE = 'route-optimizer'
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_SHA = sh(returnStdout: true, script: 'git rev-parse --short=7 HEAD').trim()
                }
            }
        }

        stage('Test') {
            steps {
                // Brings up Postgres + LocalStack + the test runner via compose.
                sh '''
                    docker compose -f docker-compose.test.yml up \\
                      --abort-on-container-exit \\
                      --exit-code-from test-runner \\
                    || true
                '''
                junit allowEmptyResults: true, testResults: 'test-results/junit.xml'
            }
        }

        stage('Build') {
            steps {
                script {
                    env.IMAGE_TAG = buildAndPushImage(service: env.SERVICE)
                }
            }
        }

        stage('Deploy-Dev') {
            steps {
                deployToEcs(service: env.SERVICE, env: 'dev', imageTag: env.IMAGE_TAG)
            }
            post {
                success { notifySlack(env: 'dev', status: 'ok',   text: "route-optimizer ${env.IMAGE_TAG} -> dev OK") }
                failure { notifySlack(env: 'dev', status: 'fail', text: "route-optimizer ${env.IMAGE_TAG} -> dev FAILED") }
            }
        }

        stage('Approval-Staging') {
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: "Promote ${env.IMAGE_TAG} to STAGING?", ok: 'Promote'
                }
            }
        }

        stage('Deploy-Staging') {
            steps {
                deployToEcs(service: env.SERVICE, env: 'staging', imageTag: env.IMAGE_TAG)
            }
            post {
                success { notifySlack(env: 'staging', status: 'ok',   text: "route-optimizer ${env.IMAGE_TAG} -> staging OK") }
                failure { notifySlack(env: 'staging', status: 'fail', text: "route-optimizer ${env.IMAGE_TAG} -> staging FAILED") }
            }
        }

        stage('Approval-Prod') {
            steps {
                timeout(time: 60, unit: 'MINUTES') {
                    input message: "Promote ${env.IMAGE_TAG} to PROD?", ok: 'Deploy to prod'
                }
            }
        }

        stage('Deploy-Prod') {
            steps {
                deployToEcs(service: env.SERVICE, env: 'prod', imageTag: env.IMAGE_TAG)
            }
            post {
                success { notifySlack(env: 'prod', status: 'ok',   text: "route-optimizer ${env.IMAGE_TAG} -> prod OK") }
                failure { notifySlack(env: 'prod', status: 'fail', text: "route-optimizer ${env.IMAGE_TAG} -> prod FAILED") }
            }
        }
    }
}
