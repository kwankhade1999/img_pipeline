pipeline {
    agent any

    environment {
        IMAGE_NAME = "manojkrishnappa/adservice:${GIT_COMMIT}"
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
                dir('src/adservice') {
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

        // Uncomment and configure once EKS cluster is ready
        // stage('Deploy to EKS') {
        //     steps {
        //         withCredentials([[
        //             $class: 'AmazonWebServicesCredentialsBinding',
        //             credentialsId: 'aws-creds'
        //         ]]) {
        //             sh '''
        //                 aws eks update-kubeconfig --region ${AWS_REGION} --name ${CLUSTER_NAME}
        //                 kubectl set image deployment/adservice \
        //                     adservice=${IMAGE_NAME} -n ${NAMESPACE}
        //             '''
        //         }
        //     }
        // }

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
