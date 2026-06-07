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

  lifecycle {
    prevent_destroy = true
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

  lifecycle {
    prevent_destroy = true
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

  lifecycle {
    prevent_destroy = true
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

  lifecycle {
    prevent_destroy = true
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

resource "aws_ecr_repository" "istio_pilot" {
  name                 = "${var.istio_image_repository_prefix}/pilot"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/pilot"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "istio_proxyv2" {
  name                 = "${var.istio_image_repository_prefix}/proxyv2"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/proxyv2"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "istio_install_cni" {
  name                 = "${var.istio_image_repository_prefix}/install-cni"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/install-cni"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "istio_ztunnel" {
  name                 = "${var.istio_image_repository_prefix}/ztunnel"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/ztunnel"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "istio_pilot" {
  repository = aws_ecr_repository.istio_pilot.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio pilot images"
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

resource "aws_ecr_lifecycle_policy" "istio_proxyv2" {
  repository = aws_ecr_repository.istio_proxyv2.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio proxyv2 images"
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

resource "aws_ecr_lifecycle_policy" "istio_install_cni" {
  repository = aws_ecr_repository.istio_install_cni.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio install-cni images"
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

resource "aws_ecr_lifecycle_policy" "istio_ztunnel" {
  repository = aws_ecr_repository.istio_ztunnel.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio ztunnel images"
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

resource "aws_ecr_repository" "teleport" {
  name                 = var.teleport_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.teleport_image_repository_name
    Purpose   = "teleport-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "teleport" {
  repository = aws_ecr_repository.teleport.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Teleport images"
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

resource "aws_ecr_repository" "pause" {
  name                 = "financial/pause"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = {
    Name      = "financial/pause"
    Purpose   = "k3s-pause-image"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "aws_load_balancer_controller" {
  name                 = "financial/system/aws-load-balancer-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/system/aws-load-balancer-controller"
    Purpose   = "aws-load-balancer-controller-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "aws_load_balancer_controller_monitoring" {
  name                 = "financial/monitoring/aws-load-balancer-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/monitoring/aws-load-balancer-controller"
    Purpose   = "aws-load-balancer-controller-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "aws_load_balancer_controller" {
  repository = aws_ecr_repository.aws_load_balancer_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 AWS Load Balancer Controller images"
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

resource "aws_ecr_repository" "observability_indexer" {
  name                 = "financial/monitoring/observability-indexer"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/monitoring/observability-indexer"
    Purpose   = "observability-indexer-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "observability_indexer" {
  repository = aws_ecr_repository.observability_indexer.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Observability Indexer images"
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

resource "aws_ecr_repository" "kyverno" {
  name                 = "financial/kyverno/kyverno"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/kyverno"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno" {
  repository = aws_ecr_repository.kyverno.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
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

resource "aws_ecr_repository" "kyvernopre" {
  name                 = "financial/kyverno/kyvernopre"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/kyvernopre"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyvernopre" {
  repository = aws_ecr_repository.kyvernopre.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
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

resource "aws_ecr_repository" "kyverno_background_controller" {
  name                 = "financial/kyverno/background-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/background-controller"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_background_controller" {
  repository = aws_ecr_repository.kyverno_background_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
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

resource "aws_ecr_repository" "kyverno_cleanup_controller" {
  name                 = "financial/kyverno/cleanup-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/cleanup-controller"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_cleanup_controller" {
  repository = aws_ecr_repository.kyverno_cleanup_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
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

resource "aws_ecr_repository" "kyverno_reports_controller" {
  name                 = "financial/kyverno/reports-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/reports-controller"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_reports_controller" {
  repository = aws_ecr_repository.kyverno_reports_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
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
