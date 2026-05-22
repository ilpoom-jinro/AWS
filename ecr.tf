resource "aws_ecr_repository" "ansible_codebuild" {
  name                 = var.ansible_codebuild_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.ansible_codebuild_image_repository_name
    Purpose   = "ansible-codebuild-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "ansible_codebuild" {
  repository = aws_ecr_repository.ansible_codebuild.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Ansible CodeBuild images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "internal_git" {
  name                 = var.internal_git_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.internal_git_image_repository_name
    Purpose   = "internal-git-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "internal_git" {
  repository = aws_ecr_repository.internal_git.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 internal Git images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "argocd" {
  name                 = var.argocd_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.argocd_image_repository_name
    Purpose   = "argocd-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "argocd" {
  repository = aws_ecr_repository.argocd.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Argo CD images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "argocd_redis" {
  name                 = var.argocd_redis_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.argocd_redis_image_repository_name
    Purpose   = "argocd-redis-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "argocd_redis" {
  repository = aws_ecr_repository.argocd_redis.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Argo CD Redis images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "prometheus" {
  name                 = var.prometheus_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.prometheus_image_repository_name
    Purpose   = "prometheus-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "prometheus" {
  repository = aws_ecr_repository.prometheus.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Prometheus images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}
