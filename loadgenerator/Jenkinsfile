pipeline {
    agent any

    environment {
        IMAGE_NAME = "manojkrishnappa/loadgenerator:${GIT_COMMIT}"
        AWS_REGION = "us-west-2"
        CLUSTER_NAME = "itkannadigaru-cluster"
        NAMESPACE     = "itkannadigaru"
    }

    stages {

        stage('Git Checkout') {
            steps {
                git url: 'https://github.com/ManojKRISHNAPPA/Microservice.git', branch: 'main'
            }
        }

        stage('Docker Build') {
            steps {
                dir('src/loadgenerator') {
                    sh '''
                        printenv
                        docker build -t ${IMAGE_NAME} .
                    '''
                }
            }
        }

        stage('Login to Docker Hub') {
            steps {
                script {
                    withCredentials([usernamePassword(
                        credentialsId: 'docker-hub-creds',
                        usernameVariable: 'DOCKER_USERNAME',
                        passwordVariable: 'DOCKER_PASSWORD'
                    )]) {
                        sh "echo $DOCKER_PASSWORD | docker login -u $DOCKER_USERNAME --password-stdin"
                    }
                }
            }
        }

        stage('Push to Docker Hub') {
            steps {
                sh 'docker push ${IMAGE_NAME}'
            }
        }

        stage('Update GitOps Deployment') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'github-creds',
                    usernameVariable: 'GIT_USERNAME',
                    passwordVariable: 'GIT_PASSWORD'
                )]) {
                    sh '''
                        if [ -d "gitops" ]; then
                            echo "gitops directory exists. Removing it..."
                            rm -rf gitops
                        fi
                        git clone https://$GIT_USERNAME:$GIT_PASSWORD@github.com/ITkannadigaru/GitOps.git gitops
                        cd gitops/base/loadgenerator/

                        git config user.email "jenkins@ci.com"
                        git config user.name "jenkins"

                        # Update image tag
                        sed -i "s|image: .*loadgenerator.*|image: ${IMAGE_NAME}|g" deployment.yaml

                        git add .
                        git commit -m "Update loadgenerator image to ${IMAGE_NAME}"
                        git push origin main
                    '''
                }
            }
        }

    }

    post {
        always {
            sh 'docker rmi ${IMAGE_NAME} || true'
            sh 'docker logout || true'
        }
        success {
            echo "Build and push successful: ${IMAGE_NAME}"
        }
        failure {
            echo "Pipeline failed. Check the logs above."
        }
    }
}
